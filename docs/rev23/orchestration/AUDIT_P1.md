# AUDIT_P1: the 3P inventory (2026-10-29)

**Verdict: APPROVED.** RR_P1 was written by a read-only Claude subagent. Its only file is RR_P1.md.

## Spot-checked against the source

- **The SEC contact break is real.** `git show 23e41c4:followup_gather.py` line 265 reads `sec_guidance.UA`. At
  `5b9ccf5`, `sec_guidance.py` has `sec_ua()` at line 23 and no `UA`.
- **The branches are as stated.** 23e41c4 is contained only in `review-2026-09/phase-6-fix-source`, `phase-6-followup`
  and `phase-6-on-rev21`.
- **The runtimes match.** I recomputed them from `n5/runs.jsonl`:

  | Task | n | Median | p90 | Max |
  |---|---|---|---|---|
  | material_events | 91 | 140 s | 210 s | 468 s |
  | risks | 45 | 140 s | 258 s | 476 s |

## Rulings

- **SPEC_m3p §0:** write a small gather on the qwen_c side, as RR_P1 recommends.
- **The task `RS2-B2-Gather-P6`** belongs to the earlier follow-up recall test (B2). It is left as it is: not 3P's to
  change. It is listed for the operator.
- **WO_O2 estimate:** about 8 tasks × 120–140 s, so roughly 16–19 minutes per name and 16–19 hours for 60 names. The
  window from about 10-31 01:00Z to 11-02 14:30Z is about 61 hours.
