# Brief R24 step 2c: the corrected ranges, the rev22 control desk, working capital (Phase 4 revision 24 v2)

## Where and how
- **Repository:** rs2-local. **Worktree:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-rev24`, branch `review-2026-10/rev24-muse`,
  head `e8b8a9b`. Work only there.
- **Never:** GPU, model or server; push, merge or deploy; delete files; edit `.env*`; change `config.json`.
- **Do not touch** `scratch\rev23\pilot_r24\`: another builder works there.
- **Commits:** small commits by pathspec, with messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest tests tools/audit_202608/tests -q`. The baseline is 3,178 passed and the 42 known
  failures; no new failure. Wait for more than 2.5 GB of free memory before the full suite.

## Read first
- `docs/review_2026-09-22/PHASE_4_AMENDMENTS.md`, "Revision 24 step 2b" (2026-10-16 09:30). **Its rulings 1, 2, 5, 6, 7, 8, 10, 12 and 18 are
  what you build.** Read the whole entry.
- `BRIEF_R24_S2b_ranges_gate.md`, and the step-2b commits `4111abf..e8b8a9b`.
- **The rebuild** (read-only, never imported by rs2), `scratch\rev23\wt-v21`:
  - `valuation/priors.py`: how `margin_target` and the ROIC level are positioned (the centre, `retention_k5_used`, `residual_k5_by_level`,
    `_level_group`, the merges and MIN_N refusals, the commodity normalization curve);
  - `valuation/priors_build/stats.py`: how `residual_k5_by_level` is measured;
  - `rev23/SPEC_rebuild.md`, Addendum I (I1, I5).
- The parity script `scratch\rev23\r24_s2b\` and its report.

## What to build
**1. The long-run margin range (ruling 1).**
- Replace the R-quantile construction in `tools/population_ranges.py` with the rebuild's `margin_target`:
  - the centre on the median-retention path at year 5;
  - the spread from `margin_retention.residual_k5_by_level` for the company's current-margin band;
  - the same cell choice, merges and MIN_N refusal (named) as `priors.py`;
  - the commodity family on the normalization curve.

  P5, P10, P25, P50, P75, P90, P95 of the year-5 operating margin level.
- **Extend the parity script** to these quantiles. Run it on the same 30 names × 2 dates, in `wt-v21`'s interpreter. Every mismatch is listed.

**2. Units (ruling 2).**
- Print the range as an operating margin, with the company's filed 8-year median operating margin (`om_tc`) and earnings margin (`m_tc`).
- Print the earnings-margin equivalents by `earnings_q = m_tc + (1 − t) × (OM_q − om_tc)`:
  - t is the record's median effective tax rate over the same window when within [0, 0.5];
  - otherwise 21%, stamped `tax_rate_statutory_fallback`.
- The gate's `long_run_margin` check uses the earnings-margin P5–P95.
- **Report a table** for UGI, MPWR, MU, LAMR, AMD, CMRE, LITE, LIND, KSS and HRTG:
  - the cohort cell, its n, `om_tc`, `m_tc`, t and its source;
  - the operating P10/P50/P90 and the earnings P10/P50/P90;
  - or the named refusal.

**3. Terminal growth and revenue CAGR (ruling 5).**
- The `terminal` table is printed as **"10-year revenue CAGR"**, context for the growth path, and it bounds the gate's `revenue_cagr_10y`. It is
  never printed as `terminal_g`'s range.
- `terminal_g` gets no population line.
- **The gate on `terminal_g`:**
  - reject at or above the discount rate (unchanged);
  - above the pack's printed long-run growth anchor (find the fact the pack prints: the growth anchor or GDP trend, and name it in your reply)
    is an outlier needing an outlier-level citation (`implausible_supported_terminal_g` / `implausible_unsupported_terminal_g`).

**4. Return on new investment (ruling 6).**
- The range is the ROIC level five years on (`roic_level` with its `residual_k5_by_level`, positioned as `priors.py` does), printed as the
  context for `terminal_ronic`. Add it to the parity script.
- Drop the `ronic` table from the briefing and the gate. Keep `ronic_fade` only if `priors.py` uses it for the same purpose; say which.
- The gate compares `terminal_ronic` with this range's P5–P95; "unlimited" is above P95.

**5. Unmeasured families (ruling 7).** For a family with no measured cohort for an input, print "no measured population for this family" for
that input. The gate annotates `no_population_cohort` and still runs the mathematics and the `terminal_g` anchor check. The TASK's citation
rule says the in-range rationale applies when there is no range.

**6. Gate citations (ruling 8).** `citation_resolves` accepts exactly what `crux_check` accepts for a crux: `pack_company` or
`fetched_page_naming_company`, with the quote found. One shared rule; reuse `crux_check`'s logic, do not copy it.

**7. The rev22 control desk (ruling 10).**
- Under `pilot_arm` `rev22`, the desk values the long run as revision 22 did:
  - the generator's margin path;
  - `long_run_margin` not required;
  - the revision-22 defaults, holds and cap, as that pack expects them.
- D2–D4 stay. Stamp `rev22_control_desk` on the desk output and the sample record.
- **Test:** a revision-22-style call (no `long_run_margin`) on the 3 saved packs under `rev22` values, and is refused under the iii arms.

**8. Working capital (ruling 12).** The working-capital deduction follows the scenario's own revenue path: the stated intensity × the change in
that path's revenue. Never the reference's path.
- **Test:** two scenarios differing only in growth get different deductions in the right direction, with hand-computed values.
- Say whether the rev22 control's deduction changes, and by how much on the 3 saved packs.

**9. Classifications and `within_p10_p90` (ruling 18).**
- Validate the three classifications against their allowed values; an invalid one is annotated `invalid_classification_<name>`.
- Compute `within_p10_p90` in code from the printed range. Keep the analyst's declared value, annotate a mismatch
  (`within_p10_p90_mismatch:<input>`), and base the citation level on the code's value.

**10. `PACK_REVISION`** stays 24 (never run yet). Append to the revision-24 history line: "ranges per rebuild I1 (margin, ROIC level), 10-year
revenue CAGR, terminal_g by anchor, working capital on own path, rev22 control desk".

## Deliverable
- The commits, the suite counts, and the extended parity report.
- The ten-name table (item 2).
- MU's and UGI's rebuilt POPULATION RANGES sections, in both P50 arms.
- The growth-anchor fact you used.
- The working-capital before and after.
- Every judgement call or gap.

Reply as text; decide nothing left open.
