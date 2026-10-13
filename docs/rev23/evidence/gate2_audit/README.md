# Gate-2 audit evidence (SPEC_rebuild AK.27-AK.31)

- `tag_consistent.py`: the tag-consistent outcome rebuild and re-score (AK.30: the version of record), and its pre-T dry test.
- `tag_consistent_drytest.json`: the dry test on quarters filed BEFORE each date (no outcome read): 482 compared, 14 differ by more than 5 pt.
- `tc_debug.py`: prints one disagreement's raw facts.

They ran from `stocks-workspace/scratch/rev23/gate2_audit/` against rs2-local `review-2026-10/gate2-run2`.
