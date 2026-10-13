# Brief: write the gate-1 freeze, then run the holdout ONCE

Written by the coordinator on 2026-10-07. Binding documents:
- `REGISTRATION_gate1_v2_DRAFT.md`: the bars, approved by the operator on 2026-10-07;
- `SPEC_rebuild.md` Addenda J–Q: the freeze contents (J10), the price and classification rules (L3, L4, M, N, P),
  and the frozen engine `c7d7a4f` (L2, N);
- the harness on branch `review-2026-10/rebuild-gate1` at the head left by the Addendum-P implementation.

## Steps
1. **Readiness:** `python -m rebuild_harness.holdout_inputs` must report `ready: true` for the 24 month-ends from
   2023-01-31 to 2024-12-31. If it does not, stop and report the blockers.
2. **Engine-unchanged proof:** `git diff c7d7a4f HEAD -- valuation` must be empty. If it is not, stop.
3. **Freeze:** write the freeze file with every Addendum J 10 content plus the later additions (D1 index, D3 documents,
   cover index, monthly fallback, the priors vintages 2022–2023 actually used, the ERP basis `engine_consistent` with
   its inputs, the crosswalk, D2 headers, seeds, package versions). Print the freeze file's content and sha256 before
   running anything.
4. **The holdout run, once:** daily raw prices (D5) with the M6 fallback; strict SIC as filed (L3); survivorship
   machinery M/N/P with the three bounds; outcomes as 12-month excess returns from the next session's open, through
   2025-12-31 for the last date (registration v2). Use the registered B1–B5 code exactly. Write to a new folder
   `scratch/rev23/gate1_holdout/`.
5. **Report:**
   - every bar under each bound;
   - PASS, FAIL or NOT DECIDED by the registered rule;
   - the B3 diagnostics;
   - B5's reported variants;
   - coverage and refusals by reason;
   - the census counts and the bounds used;
   - the ERP series used;
   - compute time.

   No interpretation is needed; the coordinator reads it.

## Rules
- **The run happens once.** The holdout lock's ledger refuses a second run. If the run crashes partway, report it and
  do NOT rerun without the coordinator's instruction (a crash with no result read is resumable; any partial result
  read makes a rerun a second look).
- **No change to any file after the freeze is written,** except output files.
- No GPU, no model.
- Never delete files or folders.
- No downloads.
- Never edit the live rs2-local tree, `.env*` or secrets; never touch `cache/DEPTH_PAUSED`.
- Use `is None`, not `or`.
- At most 4 workers; RAM is tight.
- Run `date '+%H:%M'` before timestamps.
