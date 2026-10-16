# Brief R24 step 2d: the RONIC floor removed, trajectory diagnostics, census desk tests, pilot measures (Phase 4 revision 24 v2)

## Where and how
- **rs2-local work:** worktree `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-rev24`, branch `review-2026-10/rev24-muse`, at the
  audited step-2c head (the coordinator names it).
- **Pilot tooling work:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\pilot_r24\measures.py` and its tests only.
- **Never:** GPU, model or server; push, merge or deploy; delete files; edit `.env*`; change `config.json`.
- **Commits:** by pathspec, with messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`. Wait for more than 2.5 GB of free
  memory before the full suite.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest tests tools/audit_202608/tests -q`. No new failure against the step-2c count.

## Read first
- `PHASE_4_AMENDMENTS.md`, from "Revision 24" on, **especially "Cross-check 19: replies and the coordinator's rulings"**: rulings 1, 6, 9
  and 12 are what you build; also "Revision 24 step 2c: built and audited" (items 5 and 6 below).
- `REGISTRATION_rev24_pilot.md` with amendments 1–4.
- `rev23/CROSS_CHECK_19_rev24_ranges_gate_pilot.md`.

## What to build
**1. The RONIC floor (ruling 1).** In `tools/consensus_reference.py`, `long_run_value` and `ronic_at`, shared by the desk and the reference:
- **the terminal RONIC is used as stated when above 0.** Remove `max(r, ·)` from the terminal value and the fade.
  - Below r it is annotated `terminal_ronic_below_rate` (replacing `terminal_ronic_floored_at_r`), on the desk output and the sample
    record.
  - At or below 0, the desk refuses the call by name, as a `missing` entry (a positive terminal_ronic is required).
- **The start return r_tc:**
  - used as measured when above 0;
  - annotated `ronic_start_below_rate` when below r;
  - when missing or at or below 0, the fade starts at the terminal RONIC, stamped `ronic_start_from_terminal`.
- The 1/RONIC linear fade (step 2a ruling 2) and the unlimited case are unchanged.
- **The whole long-run value's floor at 0** (`floor`) is unchanged.
- **The price-implied `terminal_ronic` block:** its search range and any assumption of a floor at r. Report what changed.
- **The tests**, at e5 1.0, r 9%, terminal g 3%, fade 5, g5 3% and 10%; hand-computed values in comments:
  - value strictly increasing over the terminal RONIC 0.5r, 0.75r, r, 1.5r and unlimited, at g > 0;
  - at g = 0, the same value for every RONIC;
  - refused at RONIC 0 and −0.05;
  - the terminal value at 4.5% equals (0.333 / 0.667) × that at 9%;
  - turn step 1's audit tests that assumed the floor into the new behaviour, and list each one you changed.
- **Report:** the effect on the saved references, the AT10c-era saved packs and the 3 saved rev24 packs (value before and after, which
  stamps fire), and on LITE and LIND with step 2a's analyst-style margins.

**2. Diagnostics, never gates (ruling 6).** In the desk's `implied` block and on the sample record:
- `terminal_value_share` (the terminal value's present value over the total value);
- `terminal_reinvestment_rate` (`terminal_g / terminal_ronic`; 0 when unlimited).

`earnings_ratio_10y` stays reported and is never a rejection reason; confirm that in a test.

**3. Census desk tests (ruling 9), on saved facts**, the KSS and HRTG fixtures from `tools/audit_202608/tests/fixture_data/rev24/`:
- **Kohl's**, trend negative: a call with `terminal_g` 0.024 and no citation is rejected `implausible_unsupported_terminal_g`; with a
  resolving causal citation it passes, annotated.
- **Heritage:** its base-year earnings sit at a peak against its 8-year median; report what the gate and the diagnostics say for a call at
  the consensus levels. Report only; no new rule.

**4. Pilot measures (ruling 12, registration amendment 4)** in `pilot_r24\measures.py`:
- **compliance per arm, with denominators:**
  - desk calls refused or malformed;
  - missing Section 12 fields (the revision-24 list);
  - invalid classifications;
  - citations unresolved;
  - crux-form failures (`no_valid_crux:*` stamps and missing cruxes on directional answer runs);
- **the three "systematic copying" tests** of amendment 4, each reported true or false with its counts;
- **the new diagnostics** (item 2) per run.

Tests use synthetic run folders with hand-computed values. Keep the existing 26 tests passing.

**5. Working capital, base-normalized (step 2c audit).** In `unbundled_dcf`'s own-path working capital, normalize the revenue scaling at the base:
`revenue_t = consensus revenue_t × (oe_t / oe_0) / (ow_t / ow_0)`, with oe_0 the scenario's base_cf and ow_0 the consensus base the oe_path was
grown from. Find it in the facts and name it; if the facts do not hold it, add it as an unprinted `long_run` member like `oe_path`.
- So an analyst base below the consensus base no longer reads as a revenue fall.
- Stamp `working_capital_release` on any scenario with a negative yearly deduction.
- **Tests:** a base 40% below consensus with consensus growth gives exactly the consensus schedule; faster growth deducts more; a growth
  path below consensus releases, stamped. Hand-computed values.
- Report the before and after on the 3 saved packs and on a MU-like normalized case.

**6. The tax label (step 2c audit, ruling 3).** On the POPULATION RANGES supporting line, label t as "the translation's rate, from the years
whose net income + tax equals pre-tax income; an estimate, see DATA's tax note".

**7. `PACK_REVISION`** stays 24. Append to the history line: "RONIC as stated (no floor at r), TV share and reinvestment diagnostics".

## Deliverable
- The commits, the suite counts, and the floor tests with their values.
- The before-and-after table of item 1.
- The Kohl's and Heritage results.
- The measures test results.
- Every judgement call or gap.

Reply as text; decide nothing left open.
