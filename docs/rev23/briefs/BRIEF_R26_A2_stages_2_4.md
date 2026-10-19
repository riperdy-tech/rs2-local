# Brief R26-A2: stages 2–4, the reveal, the memo stage and the verifier (SPEC revision 26, sections 2–4)

**Read first:**
- `docs/review_2026-09-22/rev23/SPEC_rev26_staged_analyst.md` (all of it);
- the "Revision 26 build log" at the end of `PLAN_terminal_reinvestment.md`, which has the rulings that amend the SPEC: N is 3..5, `delta_pts`
  is in percentage points, `long_run_fact_ids`, and the entity rule;
- `rs2-local/AGENTS.md`.

**Where:**
- **Branch:** `review-2026-10/r26-int`, in the worktree `scratch/rev23/wt-r26-int`. It is r26-harness (A1) merged with r26-desk (C).
- **Build on:**
  - `tools/audit_202608/r26_stages.py` (A1's runner; stages 2–4 are stubs today);
  - `tools/r26_forecast.py` (C's functions; use them, never re-implement).
- **Still in progress:** R26-B (the blind pack, `op_margin_bar` and `consensus_corrected`) is building on `review-2026-10/r26-pack`.
  - Consume its outputs through the documented names: `facts["op_margin_bar"]`, `facts["consensus_corrected"]`, and the blind pack text
    from `build_pack(..., pilot_arm="r26")`.
  - Use fixtures until B merges. The coordinator merges B.
- Commit by pathspec. Do not push.
- Never use the GPU, Ollama or a model (stub providers only); no `.env*`; no bare `git stash`.
- Every other arm stays byte-identical.

**Build:**
1. **Stage 2.**
   - The `submit_forecast` tool schema exactly as the SPEC sets it, with C's rulings.
   - **The stage-2 TASK:** state the margin basis in plain words ("filed operating margin = operating income / revenue; code converts"),
     the baseline-plus-delta rule in percentage points, N in 3..5, how a later normalization is expressed, and what each field means. Name
     no numbers.
   - **Runs:** K = 3 sessions with seeds s, s+1 and s+2, each fresh, from the blind pack, the usable dossier, the summary and the bar.
     There is one structure-repair turn per session.
   - Calls C's `validate_forecast`, `build_path`, `bridge_to_x`, `value_forecast`, `alt_paths` and `aggregate`.
   - Writes `forecasts.json`.
2. **Stage 3.**
   - **A fresh session.** It is given: the dossier; the median sample's forecast **numbers only**; its desk result; the three Base values;
     the price; the price-implied inputs from the existing solver, on the 25.2 path; `consensus_corrected` (or its not-comparable reason);
     and the diagnostics (alternative paths, consensus divergence).
   - **The stage-3 TASK:**
     - frame the reveal as an audit of the market's view;
     - state the one-revision rule and the requirement to cite a fact ID;
     - state the crux in the revision-24 form.
   - **What code accepts:** at most one `submit_forecast`; a second is refused once and the stage then closes. The crux is checked and
     resolved as today.
   - **Records:** the pre and post values and the pull ratios (C's `pull_ratio`).
   - **No call** when the samples split by direction (C's `direction_split`), or when the crux is invalid.
   - Writes `reveal.json`.
3. **Stage 4.**
   - **A fresh session.** It is given: the dossier; the **frozen** final desk table; the bridge table; the crux with its verification; the
     spread; the diagnostics; and the memo TASK.
   - **The memo TASK:** explain the locked numbers; never restate a number not in the table.
   - **The contract:** the memo and its text fields come from the model. **Every numeric contract field is filled by code.**
   - **The verifier** (code), per SPEC section 4: `memo_number_mismatch` (labelled numbers against the table, within rounding),
     `memo_verdict_mismatch`, `memo_forecast_mismatch`. Any flag makes the result non-actionable.
   - Writes `final.json`, and the verdict for the existing ledger and overlay path: `pilot_arm` r26, `desk_schema` 26.
4. **The no-call status** is carried into the verdict as `no_call` with its reasons, and is never actionable.

**Tests (scripted stub model):**
- the stage-2 schema;
- K = 3 seeding;
- the repair limit;
- each artifact's contents;
- stage 3's one-revision limit;
- the pull ratio recorded;
- the no-call triggers;
- stage 4's code-filled contract numbers;
- each verifier flag;
- end to end on a fixture name through all four stages;
- the session allow-lists (no stage sees another's reasoning);
- the full rs2 suite: the same 42 failures by name as `6bc2ad0`.

**Report (≤35 lines):** commits, files, test counts, the three TASK texts' word counts with their full text in an appended file, and
ambiguities.
