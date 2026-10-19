# Brief R26-B: the blind pack, the operating-margin bar and the basis-corrected consensus (SPEC revision 26, section 5)

**Read first:**
- `docs/review_2026-09-22/rev23/SPEC_rev26_staged_analyst.md` (all of it; section 5 is yours);
- `rs2-local/AGENTS.md`;
- the replay check at the end of `PLAN_terminal_reinvestment.md`, which lists the consensus-derived pack lines found.

**Where:** rs2 branch `review-2026-10/r26-pack` from `6bc2ad0`, in the worktree `scratch/rev23/wt-r26-pack`.
- Commit by pathspec. Do not push.
- Never use the GPU, Ollama or a model; never edit `.env*`; no bare `git stash`.
- **Every existing arm's pack must stay byte-identical** (the pinned pack tests).

**Build:**
1. **Section tags in the pack builder** (`capability_test.build_pack` and its helpers):
   - every emitted line gets an internal source class (a side list, never printed);
   - with `pilot_arm="r26"`, a **blind pack** omits the classes in SPEC section 5. Use these classes, not text search, to decide.
   - Narrative sources are filtered sentence by sentence by a single generic rule. Drop a sentence that names consensus, analyst estimates,
     price targets, the share price, market cap or a price multiple. List each drop with its source in `facts["r26_blind_drops"]`.
2. **The leak test,** `r26_leak_audit(blind_pack_text, facts)`:
   - every number of the removed classes, rendered to 1–3 significant digits, with and without `$`/`%`/`B`/`M`;
   - reports any occurrence in the blind pack that is not a filed fact (with the filed source named);
   - a unit test fails on a seeded leak.
3. **`op_margin_bar`:** per filed year the operating margin (operating income / revenue, from the fields the pack already reads; name them),
   plus min, p25, median, p75, max and last over the filed window.
   - Printed in the blind pack with the label in SPEC section 5.
   - X-basis history bar for the financial family.
   - 0.0 is a value. A missing year is stated, never filled.
4. **`consensus_corrected`** (for stage 3, never printed in the blind pack), as in SPEC section 5:
   - the base-year ratio filed/vendor EPS;
   - the [0.5, 2] and ≥ 3-analysts rules;
   - `consensus_not_comparable` with the reason;
   - X-basis margins per year;
   - the operating-basis equivalent left as a hook for R26-C's bridge inversion (call it if importable, else `pending_bridge`).
5. **`facts` sidecar keys** (`SIDECAR_ONLY`, `FACTS_VERSION` bump): `r26_blind_drops`, `op_margin_bar`, `consensus_corrected`,
   `r26_leak_audit`.
6. **The `PACK_REVISION`** marker 26 for arm `r26` only, recorded in the comment log, as R25 was.

**Tests:**
- byte identity for every other arm;
- the blind pack for MSGE, TASK and DAC (from their frozen P1–P5 in `scratch/rev23/pilot_r25/frozen_p4sf/`, read-only) contains zero
  removed-class numbers, with any exceptions listed;
- the bar arithmetic;
- the consensus correction, including the not-comparable branches;
- the full rs2 suite: the same 42 failures by name as `6bc2ad0`.

**Report (≤30 lines):** commits, files, test counts, the blind-pack size against the revision-24 pack per name, the leak-audit result per
name, and ambiguities.
