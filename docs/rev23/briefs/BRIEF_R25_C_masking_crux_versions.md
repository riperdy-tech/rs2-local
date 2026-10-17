# Brief C: revision 25 Stages 0.8, 0.9 and 0.10, masking, the crux report and the version stamps (scratch pilot tooling)

**Where to work:** a new folder `stocks-workspace/scratch/rev23/pilot_r25/`, the Stage 1 tooling. Start by copying `mask.py`,
`blind_traj.py` and `measures.py` from `scratch/rev23/pilot_r24/`. **Never modify anything in `pilot_r24/`:** its records are frozen.

**Your limits:**
- no git: scratch is not tracked, and the coordinator records hashes;
- no GPU; no rs2 changes. Two other builders own rs2 on other branches.

**Read only these:**
- `stocks-workspace/docs/review_2026-09-22/rev23/PLAN_rev25_2026-10-16.md`: 0.8, 0.9, 0.10 and Stage 1;
- the three copied files, by section.

**Your report** is at most 50 lines.

## 0.8: masking
- **`mask.py` must remove every leak listed in deviation 2** of the revision-24 pilot:
  - label words, including "Strong Buy", "Buy", "Hold", "Sell", "Avoid", "Accumulate", "Trim" and any `verdict` value;
  - margin-of-safety columns and figures;
  - momentum percentages;
  - direction phrases: "undervalued", "overvalued", "upside", "downside", "cheap", "expensive", "priced in", "below intrinsic", "above
    intrinsic", and the like;
  - per-share values and the price;
  - the arm and seed;
  - pack revision markers.
- **Build the list from the 22 pilot memos themselves** (`pilot_r24/runs/*/*/*/sample1.md`). Read them through a script that prints
  candidate residuals, not by reading whole memos.
- **`blind_traj.py`:** make it part of the tooling, called by `mask.py`'s pipeline.
- **A residual scanner,** `residuals.py`, fails on any leak pattern left in a masked memo.
- **The test:** masking all 22 pilot memos into a temporary folder leaves 0 residuals. Keep a small pytest in `pilot_r25/tests/`.

## 0.9: the crux report
`measures.py` reports two things apart:
- **candidate citations:** every citation the analyst offered, and whether each resolves;
- **the final citation that supports each directional verdict:** the crux the verdict rests on, and whether it is verified.

The pilot's "26–30% unresolved" (candidates) and "every directional call had a verified crux" (finals) must both be reproducible from the
22 pilot runs. Show the two numbers in your report.

## 0.10: the version stamps
**A module, `versions.py`,** holding four identifiers, each read from its source and never typed by hand:
- **pack:** the pack's `PACK_REVISION` marker in `_pack.md`'s first line;
- **desk schema:** the facts' `desk_schema`, or "24" when absent;
- **runner protocol:** a constant in the Stage 1 runner, `RUNNER_PROTOCOL = "r25.1"`, which you add to a stub `stage_r25.py`. Make only the
  stub that holds the constant and the stamping function; the coordinator builds the runner;
- **rubric:** the sha256 of the rubric file it is given.

**`stamp(run_dir, rubric_path)`** writes `versions.json` into a run folder. `measures.py` refuses to aggregate runs whose stamps differ
within one arm.

## Report
- the files and what each does;
- the residual count before and after;
- the two crux numbers;
- ambiguities.
