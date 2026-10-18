# Brief P4B: a one-run test of Qwen on the revision-25 bridge (arm r25_b), MSGE

## Why
D2 needs the analyst's revenue and margin path, the 25.1 bridge. The production Qwen arm (`iii_no_p50`) does not ask for it. Before
part (c) the operator ruled (2026-10-18):
- test option A, Qwen filling the bridge, on MSGE, one run;
- waive the pre-run cross-check for this test only.

The test answers one question: does Qwen v33 fill the bridge cleanly, with compliance, citations and coherence at least as good as its
revision-24 MSGE run? Muse did not (`STAGE1_R25_REPORT.md`).

## Read first
- `scratch/rev23/pilot_r25/design.py`: the Phase 4 block (`P4_*`), and how `P4_SET` adds a mode.
- `run_p4.sh`, `launch_detached_p4.sh`, `make_tree_p4.sh`, `fill_run.py`, `stage_p.py`, `stage_r25.py`, `measures.py`, `tests/`.
- `docs/review_2026-09-22/rev23/PLAN_phase4_qwen_restoration.md`.
- `STAGE1_R25_REPORT.md`, for how arm B was scored.

## Build: mode `P4_BRIDGE=1`, mirroring how `P4_SET` was added (smallest change)
1. **The arm and names:**
   - arm `r25_b`;
   - names `("MSGE",)`;
   - one run, with the seed rule of P4;
   - expected pack revision 25 and desk schema 25.1, from the existing per-arm expectations.
2. **The tree:** `tree_p4b`, at rs2 commit `8e2cb8a` (`ollama_raw` and the crux message fix). Build it like `make_tree_p4.sh`, with the
   same two config keys as the P4 tree and the same config check.
3. **Directories and names:**
   - `frozen_p4b/`, `runs_p4b/`, `logs_p4b/`;
   - the run file `run_p4b.txt`, written by `fill_run.py`;
   - the scheduled task `RS2-P4-BRIDGE`;
   - its own exit flag.
4. **Reuse, never re-collect.** MSGE's P1–P3, quote, research and evidence are **copied** from `frozen_p4/MSGE/` (never moved or
   edited). Stage P rebuilds only the pack and the leak check for arm `r25_b` on `tree_p4b`.
5. **Guard, provider and model:** as P4 (`ollama_raw`, `rs2-analyst-deep-mtp5-v33`, the runner guard).
6. **After the run, `score_p4b.py`** writes `runs_p4b/MSGE/score.json`. It records:
   - **bridge compliance:** each desk call's bridge validation result, the C1–C5 and K1–K4 outcomes, refusals by name, and
     `reason_given` where a check asked for one;
   - **the counts:** desk calls, desk errors, and malformed tool calls;
   - **citation verification:** as Stage 1 measured it;
   - **the final verdict:** label, Base, the crux and its validity;
   - **the same measures on the revision-24 MSGE run** (`runs_p4/MSGE`), side by side.

   Coherence is judged by the coordinator from the transcript, not by the script.

## Tests (system Python, the pilot `tests/`)
- **Mode selection:** P4 and P4_SET are unchanged byte for byte when `P4_BRIDGE` is unset.
- **Copy, not move:** the copied evidence hashes equal the sources.
- **The score script:** on a stored Stage 1 arm-B run fixture, if one exists.

## Limits
- **Do not launch** stage_r25 or anything that loads a model. The coordinator launches. Running Stage P is allowed only if it uses no model:
  check that, and stop before any model call.
- No GPU.
- Commit nothing in rs2-local; the pilot folder is scratch.
- No edits to `frozen_p4/` or `runs_p4/`.
- **Report (≤30 lines):** the files, the test counts, the exact launch command, and the expected GPU duration from the P4 MSGE logs.
