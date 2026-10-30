# AUDIT_S1: the equal-weight universe benchmark U (2026-10-30)

**Verdict: APPROVED.**
- **Code:** `scratch/rev23/m3o/universe.py` (new) and the marks section of `m3o_engine.py`.
- **Tests:** 73 passed (54 before plus 19 new), rerun by me.

## Checked

- **No action changed.** I reran the engine on the 09-30 dry-run map into a fresh ledger and compared it with the
  earlier dry-run ledger: the actions, qwen, verification, factor and formations lines are **identical**. The only
  difference is the PREREG_m3o hash in `inputs`: v1.2 then, v1.3 now.
- **A consequence noted:** once real lines are stored, any later PREREG amendment changes `inputs.prereg_m3o`, and the
  stop rule halts the engine. That is correct, because a rule change needs a new ledger segment (CHANGE_REGISTER), never
  a silent recomputation.
- **The universe definition:**
  - `stocks.json` rows whose `factor_scores.json` entry at the same output commit has `fct_veto` null, which is the
    scorer's own eligibility.
  - At `b9497ef`, 3,051 rows qualify, which equals the file's `scored_count` (I checked).
  - Less the 4 operator-excluded names, that leaves 3,047.
  - `stocks.json`'s `status` field is the old Tier 1 screen (4 of 6,966 pass), so it is correctly not used.
- **What U does:** the same `period_return` arithmetic as the arms. It is dropped whole for a group whose formation lacks
  prices; it is never partial.

## Operating rule (added to WO_O2 step 6)

Fetch the universe prices (`universe.py fetch <T>`, about 3,047 names in 16 chunks, Yahoo) **before** the first engine
run for that as-of date. Otherwise a marks file stored without U would stop the engine when U appears. Refetch every
formation of the group after each new fill.

## Not done (carried)

- The spread-sensitivity row (SPEC_m3s §0, item 4).
- A real-data run with U, which waits for the fetch.
