# Brief B: revision 25 Stages 0.6 and 0.7, the two-pass protocol and the memo merge

**Your workspace:**
- **Worktree:** create it with `git -C C:/Users/riper/stocks/rs2-local worktree add -b review-2026-10/rev25-twopass
  ../stocks-workspace/scratch/rev23/wt-r25-tp 4deab98` and work only there.

**Your limits:**
- commit by pathspec;
- never push, merge or deploy; no GPU, so build and test with stub models only;
- never edit `.env*` or config;
- never use a bare `git stash`.

**Read only these:**
- `stocks-workspace/docs/review_2026-09-22/rev23/PLAN_rev25_2026-10-16.md`: 0.6, 0.7, Stage 1 and the v3 additions;
- `rs2-local/AGENTS.md`.

**Read code by grep and section only.** Your report is at most 60 lines.

**Two parallel builders work on other branches. Avoid their areas:**
- builder A: `bridge_checks.py`, the desk's classification checks, `_tools_desk25`;
- builder C: the scratch pilot tooling.

Keep your edits to the analyst loop (`analyst_tools.py` outside `_tools_desk25`), the pack builder (`capability_test.py`),
`consensus_valuation.py`, and `contract_fill.py`'s new change-log fill.

## 0.6: the two-pass protocol (arms `r25_b` and `r25_c`; every other arm unchanged)
**The design.** The arms are identical except for one thing:
- **B** sees consensus from pass 1;
- **C** sees it only at the start of pass 2.

The facts, evidence, settings, tools and prompts are otherwise identical, and every word of the pass-2 message is the same apart from the
consensus block.

**Pass 1:**
1. **The analyst's task:** research as now, then make at least one complete desk run, i.e. one that returns `scenario_dcfs`.
2. **The record:** the inputs of the last complete pass-1 run are recorded as `pass1_inputs`.
3. **The gate:** pass 2 cannot open before a complete pass-1 run. A sample whose budget ends without one is stamped
   `two_pass_breach:no_pass1` and is not usable.

**Pass 2:**
1. **The harness injects one fixed message:**
   - "Pass 2: reconcile your preliminary forecast with everything in the pack.";
   - for arm C only, it also carries the withheld consensus block, verbatim.
2. **The analyst** then runs the final desk calls and writes the memo and contract.

**What the run records:**
- **The change log is code-computed** from `pass1_inputs` against the final run's inputs: each changed input, with its pass-1 and final
  value.
- **The analyst's reasons** come in a new contract field, `reconciliation_reasons` (a list of {input, reason}).
- **Five new verdict-row fields:** `pass1_inputs`, `change_log`, `reconciliation_reasons`, `two_pass_arm` and `consensus_shown_pass1`
  (true or false). Each is added to its owner's schema.

**What arm C withholds in pass 1:** every pack element derived from analyst estimates. Enumerate them from the code; expect at least:
- DATA 8 consensus estimates;
- the DEFAULTS `levels` and any consensus-path growth;
- `next_fy_revenue_growth` where it comes from estimates;
- street targets or fences, if printed;
- the consensus fields in GUIDANCE, if any.

**Not withheld:** filed facts, company guidance, price, population ranges and research.

**How C's packs are built and frozen:** the pass-1 pack, plus the withheld block as a separate artefact, each frozen for the runner.

**List every element withheld, with its source line, in your report for the coordinator's ruling.**

## 0.7: the memo merge after a crux follow-up
- **The defect:** the pilot lost 4 memos when the crux follow-up's reply said, in effect, "unchanged from prior".
- **The fix, deterministic and in code:**
  - the final memo is the answer memo, with each SECTION replaced by the follow-up's section only when the follow-up gives real content
    for it;
  - **a section counts as a placeholder** when, after whitespace is stripped, it is empty, or under 200 characters and matches a fixed
    phrase list ("unchanged", "same as", "as above", "as before", "see prior", "no change"); the prior section is kept;
  - the contract JSON is taken from the follow-up when it is complete, else from the answer;
  - each kept or replaced section is listed in `memo_merge` on the verdict row.

## Tests (stub model; targeted only)
- **Pass gates:** pass 2 cannot open without a complete pass-1 run, and the breach stamp is set.
- **The arms differ only by consensus:** B and C pass-2 messages differ only by the consensus block, compared byte for byte.
- **Withholding:** C's pass-1 pack contains none of the withheld elements, checked by grep of the values, not only the headers.
- **The change log:** built from the inputs, with no model text involved.
- **The memo merge:** keeps a section given "unchanged from prior", and replaces it with real content.
- **Other arms unchanged:** iii and rev22 pack bytes and prompts are unchanged, on a fixed fixture.

## Report
- commits;
- files;
- test counts;
- the withheld-element list;
- ambiguities, each marked for a ruling.
