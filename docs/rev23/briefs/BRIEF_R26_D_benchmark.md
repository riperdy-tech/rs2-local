# Brief R26-D: the revision-26 benchmark mode, masked extracts, the scorecard and the canary (SPEC revision 26, sections 6 and 8)

**Read first:**
- `SPEC_rev26_staged_analyst.md`, sections 6 and 8, which hold the panel, the draw and the pass rules;
- `PLAN_terminal_reinvestment.md`, the "Revision 26 build log";
- `scratch/rev23/pilot_r25/design.py`, with how the `P4_BRIDGE` and `P4_SF` modes were added, and `stage_p.py`, `stage_r25.py`, `fill_run.py`
  and `score_p4sf.py`;
- the memory rule "smoke test before GPU runs".

**Where:**
- The pilot folder `scratch/rev23/pilot_r25/` (scratch, no git).
- The rs2 integration tree is `review-2026-10/r26-int` @ `372a6dc`.
- Never use the GPU, Ollama or a model; never launch anything. The coordinator launches.
- Never edit `frozen_p4*`, `runs_p4*`, `evidence*` or `tree_p4*`.

**Build: mode `P4_R26=1`** (refused together with any other P4 mode):
1. **The tree:** `tree_p4r26` at the integration head, with the P4 config keys and the config check, as the P4_SF tree has them.
2. **The panel and draw** (SPEC section 8):
   - the 7 restoration names reuse their frozen P1–P4, quote, research and evidence, **copied**;
   - the 5 drawn names (OGE, HNRG, PTCT, LPG, ITGR, with skips by the draw rule) go through stage P as a new name did in the restoration;
     that needs P3 research, which uses the GPU, so it is done by the coordinator's launch;
   - the holdout list is recorded but not run.
3. **Two run kinds:**
   - `stage1` runs once per name, then freezes `dossier.json` (with its hash) into `frozen_p4r26/<T>/`. It never re-runs a frozen name.
   - `stages24` re-runs stages 2–4 from the frozen dossier into `runs_p4r26/<iteration>/<T>/`. The iteration number is in the run file.
4. **A smoke test, `smoke`.** One name (MSGE), and only the first model turn of stage 1 and of stage 2, then stop. Report:
   - that the model answered;
   - that a tool call was parsed;
   - no server_error or guard;
   - the logged turn file exists.
   It must pass before any `stage1` or `stages24` run is allowed: the run file records the smoke result and its tree hash, and the runner
   refuses otherwise.
5. **Fail fast.** The runner stops the whole run at the first sample whose failure is a code defect (server_error, a named provider
   refusal, a traceback, an R26 input error). It stops before the next name and writes the reason.
6. **The canary run.** On MSGE, TASK, DAC and BUD, `stages24` with stage 3's revealed consensus margins shifted by +3 and −3 points (two extra
   stage-3 and stage-4 runs per name, from the same stage-2 output). Reported as pull ratios toward the shifted numbers.
7. **`mask_extract.py <iteration>`:** per name, a masked extract containing the dossier facts and summary, the stage-2 forecast inputs and
   labels, the memo text and the contract's text fields.
   - Removed: every value per share, the price, every verdict word, the frozen table, the spreads and the run metadata.
   - A test proves no number from the frozen table's value rows, and no verdict word, survives.
8. **`READER_RUBRIC.md` and `reader_prompt.txt`:** the SPEC section 6 rubric, with its 4 criteria, each scored coherent, questionable or
   incoherent with quotes. The reader returns JSON per name. The prompt names no results file and no plan file.
9. **`score_p4r26.py <iteration>`:** every SPEC section 6 metric, computed from the run artifacts, plus the two readers' JSON and the
   coordinator's adjudication file. It prints the pass rule, item by item, with values, and PASS or FAIL.

**Tests (system Python, the pilot `tests/`):**
- other modes unchanged;
- copies equal their sources;
- smoke gating;
- fail-fast stops;
- the canary shift arithmetic;
- the mask removing all value, price and verdict content (on the P4_SF runs as fixtures);
- the scorecard on a fixture iteration.

**Report (≤30 lines):** files, test counts, the exact launch commands for smoke, stage 1 (12 names) and stages24, and the expected GPU time per
kind.
