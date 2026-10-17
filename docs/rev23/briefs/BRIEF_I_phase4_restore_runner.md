# Brief I: the runner for the Phase 4 restoration (Qwen on the revision-24 desk, via `ollama_raw`)

**The plan:** `docs/review_2026-09-22/rev23/PLAN_phase4_qwen_restoration.md`. Read it first.

**Where:** `stocks-workspace/scratch/rev23/pilot_r25/`, extending its existing Qwen mode (brief G, `PILOT_MODEL=qwen38q4`) with a new mode,
`PILOT_MODEL=qwen38q5raw`.

**The limits:**
- Muse's Stage 1 artefacts and the q4 Qwen mode's folders stay untouched: `tree/`, `runs/`, `frozen/`, `masked/`, `run_r25.txt`,
  `tree_qwen/`, `runs_qwen/`;
- no GPU and no model calls (the coordinator launches);
- no scheduled-task registration, no git in scratch, no rs2 edits.

**Your report:** at most 40 lines.

## Build
1. **The tree, `tree_p4/`:** a detached rs2 worktree at **`141c413`** (branch `review-2026-10/ollama-raw`). Its config is the Muse tree's
   with only:
   - `depth_provider` "ollama_raw";
   - `depth_model` "rs2-analyst-deep-mtp5-v33".

   `tree_config.py` refuses any other difference.
2. **The design:** arm `iii_no_p50` only, seed 2501, two runs: MSGE, then the new name. Runs go to `runs_p4/`, pins to `run_p4.txt`, and
   logs to `logs_p4/`.
3. **The new name** comes from `scratch/rev23/phase4_restore/DRAW_ORDER.json`, in order:
   - stage P (P1–P5) for the `iii_no_p50` arm only;
   - **if its frozen facts show `long_run.x_L` ≤ 0, or no positive base-year earnings,** record it in `logs_p4/draw.log`, leave its folder
     as is, and take the next name in order. Never skip by any other rule;
   - its frozen data go to `frozen_p4/<T>/`.
4. **MSGE:** reuse `frozen/MSGE/` (P1–P3, the quote, the research brief and the evidence), read-only, copied into `frozen_p4/MSGE/` and
   pinned. **Re-run only P4, discovery,** on the analyst model in this mode (Qwen via `ollama_raw`), then P5 for `iii_no_p50`.
5. **Discovery on Qwen:** P4 runs `catalyst_research.run` in the `tree_p4` tree, so it goes through the tree's provider. Confirm in the
   code that discovery calls go through `llm_provider` and therefore through `ollama_raw`. Say if they do not.
6. **The guard in this mode:**
   - allow exactly the Ollama-shipped runner, a llama-server whose executable path is
     `%LOCALAPPDATA%\Programs\Ollama\lib\ollama\llama-server.exe`;
   - refuse any other llama-server;
   - refuse any Ollama model loaded other than `rs2-analyst-deep-mtp5-v33` and `rs2-research` (research, P3 for the new name);
   - at the end, unload ours by name.

   This fixes brief G's false positive.
7. **The version stamps** gain `provider` "ollama_raw", the template sha256 and the Ollama version.
8. **Commands:** `stage_p.py all` and `stage_r25.py all`, each with `PILOT_MODEL=qwen38q5raw`, plus the register script with
   `-Model qwen38q5raw`, task name `RS2-P4-RESTORE`. **Print them; do not register.**
9. **The readiness loop** (any server or engine wait) fails fast when the server process has exited. It must not poll a dead port.

## Tests
- the config diff;
- the guard (Ollama's own runner allowed; a foreign llama-server refused; a foreign Ollama model refused);
- the draw rule (a name with `x_L` ≤ 0 is passed over and logged);
- MSGE re-runs only P4 and P5, and its P1–P3 pins equal Muse's frozen ones;
- every existing test still passes.

## Report
- the files;
- the tests;
- the commands;
- the discovery-path confirmation;
- ambiguities.
