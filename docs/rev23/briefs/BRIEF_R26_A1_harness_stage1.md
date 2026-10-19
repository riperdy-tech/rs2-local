# Brief R26-A1: per-turn logging, the stage runner skeleton, and stage 1 (`register_facts`, the fact checks, `dossier.json`) (SPEC revision 26, sections 0–1)

**Read first:**
- `docs/review_2026-09-22/rev23/SPEC_rev26_staged_analyst.md` (all of it; sections 0 and 1 are yours, and section 4's artifact flow shapes
  the runner);
- `rs2-local/AGENTS.md`;
- the analyst loop in `tools/audit_202608/analyst_tools.py` (`chat_with_tools`, `_compact_history`, `tool_message`, the snapshot writer);
- `consensus_valuation.py` (how a run starts from a pack);
- `ollama_raw.py`.

**Where:** rs2 branch `review-2026-10/r26-harness` from `6bc2ad0`, in the worktree `scratch/rev23/wt-r26-harness`.
- Commit by pathspec. Do not push.
- Never use the GPU, Ollama or a model (test with stub providers); no `.env*`; no bare `git stash`.
- **Every existing arm's request bytes and outputs must stay identical** (the existing replay and pin tests).

**Build:**
1. **Logging** (SPEC section 0), for the `ollama_raw` provider in every arm: `turns/<stage>_<n>.json` and the per-run SYSTEM and template
   hashes. It is additive files only; it never changes a request.
2. **The stage runner** `tools/audit_202608/r26_stages.py`:
   - four separate sessions (`stage1` .. `stage4`), each starting from a fresh message list built **only** from the artifacts SPEC names;
   - artifacts written under the run directory: `dossier.json`, `forecasts.json`, `reveal.json`, `final.json`;
   - stage 1 is implemented now. Stages 2–4 are stubs with the documented interfaces, filled in by brief A2, which uses R26-C's functions.
3. **Stage 1:**
   - the `register_facts` tool schema, per SPEC section 1, including `done: true` and the research summary;
   - the three code checks (quote verbatim, entity/metric proximity within ±300 characters, value in quote), with the exact normalization
     documented;
   - the `usable` rule;
   - the `incomplete` marking.
   - Sources are resolved against the evidence store and the pack the session saw: `pack:<section id>` needs section IDs. Coordinate with
     R26-B's tag classes by reading its branch if it exists; otherwise define a stable section ID per pack heading and document it.
   - **The stage-1 TASK text:** research, then register the facts the valuation will need, each with its exact quote. No valuation in this
     stage.
4. **Arm `r26` plumbing:** the provider, model and config are as for P4. The runner is invoked by `consensus_valuation.py` when
   `pilot_arm == "r26"`.

**Tests (stub model):**
- the logging files and hashes;
- that logging does not change requests (byte equality against a pre-change capture);
- each fact check, including normalization, the proximity window and the value forms;
- the `usable` rule;
- a stage-1 end to end with a scripted stub model, producing `dossier.json`;
- the full rs2 suite: the same 42 failures by name as `6bc2ad0`.

**Report (≤30 lines):** commits, files, test counts, the `register_facts` schema as built, and ambiguities.
