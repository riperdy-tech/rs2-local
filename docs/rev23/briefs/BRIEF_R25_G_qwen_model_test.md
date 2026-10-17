# Brief G: the Stage 1 runner, model-test mode for Qwen 3.8 (plan v7)

**Where:** `stocks-workspace/scratch/rev23/pilot_r25/`.

**The limits:**
- **Never change** what Muse's Stage 1 used: `tree/`, `runs/`, `frozen/`, `run_r25.txt` and the masked folder are read-only to you;
- no GPU, no model calls, no scheduled-task registration, no git in scratch, no rs2 edits.

**Read first:**
- `docs/review_2026-09-22/rev23/PLAN_rev25_2026-10-16.md`, section v7;
- `stage_r25.py`, `pilot_lib.py`, `tree_config.py`, `make_tree.sh`, `design.py` and `fill_run.py`, by section.

**Your report:** at most 40 lines.

## Build a model mode, selected by one variable: `PILOT_MODEL=qwen38q4` (absent means Muse, exactly as now)
1. **A second tree, `tree_qwen/`:** a detached rs2 worktree at `9ed16fc`. Its `config.json` is the Muse tree's with only these changes:
   - `depth_provider` "ollama";
   - `depth_model` "rs2-analyst-deep-mtp5-q4-v33".

   `tree_config.py` gains this mode and refuses any other difference, printing the diff against `tree/config.json`.
2. **The design:**
   - step 1: MSGE `r25_b` s2501, then MRP `r25_b` s2501;
   - step 2: arm B on all 8 names in draw order, plus the CWEN and MSGE repeats at s2502.

   Select the step with `stage_r25.py all --step 1|2`. Runs go to `runs_qwen/<T>/<arm>_s<S>/`. The pins go to `run_qwen.txt`, made by
   `fill_run.py` in this mode.
3. **The same frozen artefacts.** The packs, the evidence and quotes, and C's withheld files come from `frozen/`, read and pinned. They
   are never rebuilt; there is no stage P in this mode.
4. **The guard in this mode:**
   - refuse any llama-server process;
   - refuse any Ollama model loaded other than `rs2-analyst-deep-mtp5-q4-v33` (`ollama ps`);
   - after a run, record VRAM and `ollama ps`;
   - **never stop another process.** At the end, unload our own model (`ollama stop <tag>`).
5. **Version stamps:** `versions.json` gains `"model": "rs2-analyst-deep-mtp5-q4-v33"` and `"provider": "ollama"`. Muse runs keep their
   stamps (absent means Muse).
6. **Everything else unchanged:** the failure classes, defects, timeout, `run_log.jsonl` and verdict handling are as Muse's.
7. **Launch:** `register_stage1_task.ps1` gains `-Model qwen38q4 -Step 1|2`, using its own task name `RS2-Stage1-R25-QWEN`. Print the
   commands; do not register.

## Tests
- the config diff (only the two keys);
- the Muse mode is byte-identical in behaviour: the existing 36 tests pass;
- the step lists;
- the guard refusing a foreign Ollama model and a llama-server;
- the output folder separate from `runs/`.

## Report
- the files;
- the tests;
- the commands to make the tree, fill the pins, check and launch step 1;
- ambiguities.
