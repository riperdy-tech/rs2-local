# Brief R24.2: the reference shown only after the analyst commits (Phase 4 revision 24, `PHASE_4_REV24_MUSE.md`)

## Where and how
- **Repository:** rs2-local. **Worktree:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-rev24`, branch `review-2026-10/rev24-muse`
  (from the frozen Phase 4 analyst, `review-2026-09/phase-4` at `e82a08b`: revision 21 `f5a540c` and revision 22 `412578d`). Work only
  there.
- **Never:** push, merge, deploy; start a GPU run, a model or llama-server; touch `config.json`'s `depth_provider` (R24.1 is the coordinator's);
  delete files; edit `.env*`.
- **Commits:** by pathspec, with messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest tests tools/audit_202608/tests -q`. The baseline has 42 known failures; record
  the counts before and after, and **no new failure** is allowed.
- **Memory:** wait for more than 2.5 GB free before the full suite.

## Read first
- `C:\Users\riper\stocks\AGENTS.md` and `rs2-local/AGENTS.md` (the standard of proof; non-negotiable 7 on pack revisions).
- `stocks-workspace/docs/review_2026-09-22/PHASE_4_REV24_MUSE.md` (the work order).
- `rev23/defect_census.md`, section A1: why the analyst must not see the reference before committing.
- `PHASE_4_AMENDMENTS.md`, revision 21 part S (the crux follow-up), which stage B is modelled on.
- **The exposure map below.** It is complete and verified; build exactly to it.

## The exposure map: every place the CONSENSUS-IMPLIED VALUE (CIV) reaches the model
| Site | Stage A |
|---|---|
| `capability_test.py:3629-3639`, the DATA 8 CIV line and its fence `[$lo, $hi]` | **omit** |
| `capability_test.py:3680-3681`, "CONSENSUS-IMPLIED VALUE: not available — reason" | **omit** |
| `capability_test.py:3662-3670`, the BASE WINDOW CHECK quoting the CIV and the fence side | **print without** the CIV quote and fence side; keep the rest |
| `pack_facts.py:969-985`, the DEFAULTS `consensus_implied_value` line (value, FAR band, fence text) and the `reference_status` line | **omit** |
| `capability_test.py:4074`, the TASK naming the CIV as non-crux context | **remove** that clause |
| `analyst_tools.py:226`, the `guidance_deviation_reason` schema text ("Base value outside 0.75-1.33 of the reference") | **remove** the field from the stage-A tool schema |
| `financial_model_tool.py:2138-2150`, the **R10 gate** (Base outside the FAR band of the CIV, so a refusal that needs `guidance_deviation_reason`, with the ratio in its text) | **off** in stage A |
| `financial_model_tool.py:2156-2165`, the unit-ratio note against the CIV or the price | **against the price only** in stage A |

**Kept unchanged:**
- the consensus forecasts: DEFAULTS `levels` year1, year2, bull2 and bear2 (`pack_facts.py:988-992`) and the R11 gate on them;
- `reference_base_b` (a filed base-year figure);
- the price-implied block (`capability_test.py:4008-4024`);
- the facts: `consensus_implied_value`, `reference_status` and `levels` are still **computed and stored** in the facts and the sidecar, for
  stage B and the records;
- every post-answer consumer (`consensus_ratios.base_to_civ`, `rule_flags`, `depth_pipeline`'s row fields).

**Watch out:** `pack_facts.py:140-212` re-parses the CIV from pack text during replay. With the line omitted it must take the CIV from the
facts or sidecar instead, never from text. Test the replay parity.

## Stage B: one turn, after the final memorandum (and after any crux follow-up)
**1. The message.** Code sends, once (`REFERENCE_REVEAL`):

> "For comparison only: the CONSENSUS-IMPLIED VALUE (what Wall Street's forecasts imply through a fixed formula) is $X per share; its
> inputs: \<the pack_line text that stage A omitted\>. Your Base is $B. Reply KEEP if your valuation stands. You may revise only an input for
> which you have evidence you did not use before: call the desk once with your answer-run inputs, changing only those inputs, and add
> `reference_revision`: a list of {input, old, new, citation: {source, quote}}. The source must be a PRIMARY P# item or a filing quoted
> exactly. The reference itself is never a reason."

**2. Desk support.**
- `run_financial_model` accepts `reference_revision` **only during stage B**.
- One extra desk call is allowed if the desk was used up.
- Inputs that are not listed in `reference_revision` must equal the answer run's, or the desk refuses (reuse the crux follow-up's
  changed-input refusal).

**3. The guardrails (code-enforced). Each failure keeps stage A's answer run as the final run, and records the reason:**
- **G1:** every changed input carries a citation whose quote verifies. Reuse the crux check's quote verification against the pack, PRIMARY
  items and fetched pages.
- **G2:** each citation's quote is **new**, i.e. not present in any stage-A tool call or in stage A's memorandum text.
- **G3:** if the revised Base moves **toward** the CIV by more than 10% of stage A's Base, G1 and G2 must hold for **every** changed input (no
  partial).
- **G4:** a revised Base more than **25%** from stage A's Base in either direction is **rejected** outright (`reference_revision_too_large`).
  The name is flagged for a re-run, not patched.
- **G5:** a reply that is neither KEEP nor a single valid stage-B desk call (prose arguing a new number, two calls, a missing list) means
  stage A stands (`reference_revision_malformed`).

**4. The record** (on the sample and carried to the verdict through the existing card and `band_verdict` path; every new field goes into
`extract_scorecard`'s whitelist and the contract, non-negotiable 5):
- `base_iv_stage_a`, `base_iv_final`;
- `reference_revision`: {fired, outcome ∈ keep | revised_accepted | revised_rejected, guard_failed, changed_inputs, toward_civ, civ, base_over_civ_a,
  base_over_civ_final};
- the full stage-B reply text in the run folder.

**5. When stage B does not fire:**
- the CIV is not available (`reference_status` not ok): the record says `not_available` and nothing is sent;
- the sample failed or is a stub;
- the server erred.

## Also
- `PACK_REVISION` is set to 24, with the history line: "Revision 24 (PHASE_4_REV24_MUSE.md R24.2): the CONSENSUS-IMPLIED VALUE is shown only after
  the analyst commits (stage A without it, stage B reveal with code-enforced revision guardrails); the R10 gate is off."
- The charter and SYSTEM files are **unchanged**. The reveal is a harness message, as revision 21's follow-up is.

## Tests (add them; each fails without the change)
- **The stage-A pack** has no CIV value, no FAR band and no fence text, while the facts still hold the CIV. Run it on 3 saved real packs, re-built
  at revision 24 from their facts.
- **Replay parity:** `pack_facts` gets the CIV from the facts, not the text.
- **R10** does not fire in stage A. The unit note compares with the price.
- **Stage B fires** once after the memorandum, and never on a stub, a failure or `not_available`.
- **G1–G5**, each with a fake model transcript: accepted; rejected for no citation; rejected for an old quote; a toward-CIV revision with one
  uncited input rejected; a revision over 25% rejected; malformed means stage A stands; KEEP keeps.
- **The record fields** reach the verdict row.
- **The crux follow-up** still works, and runs before stage B.

## Deliverable
The branch with its commits, and a reply as text (no report file) holding:
- the changes;
- the suite counts before and after;
- one example stage-A pack excerpt (DATA 8 and DEFAULTS) and the exact stage-B message, for a real saved pack;
- every judgement call or gap.

Decide nothing this brief leaves open; list it.
