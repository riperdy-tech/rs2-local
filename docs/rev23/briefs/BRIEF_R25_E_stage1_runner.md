# Brief E: the revision 25 Stage 1 runner

**Where:** `stocks-workspace/scratch/rev23/pilot_r25/`, which already holds the masking, crux and versions tooling from brief C. Copy what
you need from `scratch/rev23/pilot_r24/` (`design.py`, `make_tree.sh`, `prep.sh`, `stage_p.py`, `stage_r.py`, `fill_run.py`,
`pilot_lib.py`, `tree_config.py`, `launch_detached.sh`, `tests/`) and adapt it. **Never modify `pilot_r24/`.**

**Your limits:**
- no GPU, no model calls, no network fetches: stage P and stage R are launched by the coordinator, not you;
- no git in scratch; no rs2 edits.

**Read first:**
- `docs/review_2026-09-22/rev23/PLAN_rev25_2026-10-16.md`: sections v3–v6 and "Stage 1";
- `scratch/rev23/stage1_names/STAGE1_NAMES.json`;
- the pilot_r24 scripts' docstrings.

**Code by section.** Your report is at most 50 lines.

## The design (`design.py`, held to plan v5 and v6 by a test)
- **Names:** in `STAGE1_NAMES.json` order: CWEN, MSGE, MRP, EQNR, FTNT, LIND, LFST, STT.
- **Arms:** A = `iii_no_p50` (revision 24 as it ran), B = `r25_b`, C = `r25_c`.
- **Order:** within a name the arms rotate by name index, as in pilot_r24's `design.py`.
- **Seeds:** base 2501; the repeats use 2502, for CWEN and MSGE in B and C, run directly after their name's three runs.
- **28 runs** in all.
- **A name whose family has no measured population** (it prints no POPULATION RANGES) still runs all three arms. Record which names print
  none; do not drop or reshape runs.

## The tree
`make_tree.sh` creates a detached rs2 worktree at **`9ed16fc`** (branch `review-2026-10/rev25-bridge`), with its `config.json` set
exactly as pilot_r24's tree:
- llamacpp;
- the same model, server pins, context, sampling, think and budgets.

Diff the two configs and report every difference. **There must be none** apart from paths.

## Stage P (per name)
As pilot_r24:
- enrich;
- the frozen quote;
- forced research;
- discovery;
- the frozen evidence store;
- the three arm packs, built with `pilot_arm` set.

**For C, also freeze** `_withheld_consensus.md` and `_withheld_elements.json` beside its pack (`capability_test.split_consensus`).
Stage R refuses a C run without them.

**Stage P's check prints, per name:**
- each pack's revision marker;
- `desk_schema`: absent for A, 25.1 for B and C;
- whether C's pass-1 pack holds any withheld value, found by grepping the values from `_withheld_elements.json`. Any hit refuses.

## Stage R (per run, in design order)
- As pilot_r24: DISARM, skip finished runs, the pins, the guard, the server check, the timeout and `run_meta.json`.
- **The plan v4 failure classes.** These are final outcomes, recorded and never re-run: a reason loop, an exhausted budget, an unresolved
  fail, `two_pass_breach`, a lost memo, a refused contract.
- **Defects** (an exception or crash in the runner or desk code, a server or pin failure, a missing or changed frozen artefact) stop the
  runner. The run folder becomes partial, and a re-run uses the **same seed**. `run_meta.json` records the class.
- **`versions.stamp(run_dir, rubric_path)`** after each finished run. The rubric path is
  `docs/review_2026-09-22/rev23/REGISTRATION_rev25_stage1.md`, written by the coordinator. Refuse to start if it is absent.
- **`stage_r25.py`** (the brief C stub) becomes the real runner, keeping `RUNNER_PROTOCOL = "r25.1"`.

## Check mode and tests
- **`python stage_r25.py check`:** the pins, the guard, every frozen artefact and the design, without running anything.
- **Tests:**
  - the design against plan v5 and v6;
  - the failure-class mapping, each class;
  - the C withheld-file refusal;
  - the version stamp written;
  - the config diff empty.
- **A dry run with the pilot_r24 stubs** (`stubs/`), as pilot_r24's tests did, if they allow it without GPU.

## Launch support
`launch_detached.sh` registers a scheduled task with a hidden wrapper so the run survives a Claude app restart (as pilot_r24 did). Name
the task `RS2-Stage1-R25`. **Do not register it.** Print the command for the coordinator.

## Report
- the files;
- the test counts;
- the config diff;
- the exact launch commands for stage P and stage R;
- ambiguities.
