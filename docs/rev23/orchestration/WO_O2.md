# WO_O2: the 2026-10-30 formation, contemporaneous Qwen analyses (Claude executes, 2026-10-31 to 11-02)

**Goal:** every A0 `research_now` name of the 2026-10-30 formation has a complete qwen_c run, hashed and logged,
before the 2026-11-02 open (14:30Z, after the US clock change), or is visibly `analysis_pending` / `analysis_incomplete`
(SPEC_m3o §3.3). This is the first formation whose Qwen analyses precede the fill.

**Time-critical:** an unrecorded formation is forward evidence lost for good. On the GPU it ranks after the 3N DEV run
and before 3N FRESH (SPEC_m3o §9).

## Code and roots

- **Code:** rs2-local `review-2026-10/m3n-v6` at `4bc9425` (builder v7, AUDIT_N6 and its addendum; the `find_prior` fix).
- **Worktree:** a new one, `scratch/rev23/wt-m3o`, on a new branch `review-2026-10/m3o` made at `035ef96`, fast-forwarded to `4bc9425`. Its own
  `cache/m3m` holds this formation's store, packets, runs and ledger. Formation runs never share a ledger with 3N runs,
  so `find_prior` can only find an earlier formation run of the same ticker.
- **Scripts:** `scratch/rev23/m3o_run/` (`o2_decide.py`, `o2_packets.py`, `o2_run.py`, `run_o2.cmd`, `launch_o2.vbs`,
  `register_o2_task.ps1`), modelled on the 3N `n5_*` tools (lock, two attempts, resumable, a finished flag).

## Steps

1. **Decide.** After the Friday 10-30 price-refresh run completes (expected about 10-31 01:00Z):
   `git fetch origin` in stock-screener (moves `origin/*` only); `check_new_runs.py` (archive + verify);
   `o2_decide.py` applies `forward_ledger.decision_for` (imported from `m3l_forward`, unchanged) to name the decision
   run, T and the book, and writes `m3o/inputs/formation_2026-10-30.json` with `run_dir: null` for every name.
   - A verifier failure stops here and is recorded. It is never worked around.
2. **Packets.** `o2_packets.py` builds one v6 packet per name: regime `verified`, `--online` (SEC, standing approval),
   `--commit` = the output commit, `--verified-record` = step 1's check file, `--screener-repo` = the stock-screener
   checkout (read through git only).
   - Skip SENEA, SENEB, MOV, MG (`operator_excluded`).
   - A refused packet makes that name `analysis_incomplete`, with the refusal.
   - Record each packet's sha256 and annotations, and the `trimmed:` and `gc_passages_omitted` counts.
3. **Smoke.** One real full run on the first name (all seven tasks plus `material_events`). Read its manifest and
   statuses. A code defect stops the batch before the long run.
4. **Run.** `o2_run.py` through the scheduled task and the hidden VBS (never as a child of this session): one full
   run per name, seed base 1000, two attempts at most.
   - `gpu_busy` means wait and retry (GPU standing go: never ask; wait if another session or a game holds the card).
   - It updates `run_dir` and `attempts` in the formation map as each run finishes.
   - About 16–19 minutes per name (about 8 tasks at 120–140 s; AUDIT_P1), so 16–19 hours for 60 names, inside a window of about 61 hours.
5. **Before the fill open:**
   - Rerun `o2_decide.py`. If the decision run has changed (a later verified run before the open), the names analysed at
     the earlier T are re-queued at the new T and stay `analysis_pending` until they are rerun.
   - Freeze the map: hash it, and record the hash in LOG with the UTC time.
   - **Witness (SPEC_m3s WO_S4).** Before 14:30Z, commit a one-line file
     `docs/rev23/witness/formation_2026-10-30.txt` (the map's sha256, the run id, T, and the count of complete, pending
     and incomplete names) to rs2-local `docs/rev23-records` and push it. GitHub's push time is then an independent
     witness that the analyses preceded the fill (PLAN W.4). The file holds hashes only.
6. **After the fill:** `forward_ledger.py` appends the formation. Its run id and book must equal the map's; a
   difference is a stop. Then fetch the universe prices (`m3o/universe.py fetch 2026-10-30`; AUDIT_S1), and only then
   run `m3o_engine.py` (WO_O1), which writes the formation's lines and the marks with U.
7. **Remove the scheduled task** when the batch is done.

## Acceptance

| Test | Pass |
|---|---|
| Every book name has a map row | the count equals the book, excluded names included with their reason |
| Analyses precede the fill | the map hash is pushed (GitHub push time) before 14:30Z 11-02; each `run_dir`'s manifest `finished_at` is before it, or the name is pending |
| Decision run agrees | forward_ledger's formation equals the map's run id and book |
| Records recompute | every run's manifest and analysis sha256 recompute (as M-REC) |
| Nothing else changed | no screener, overlay, `rn_depth`, KIS or schedule change other than the temporary task, which is then removed |

## Report

`RR_O2.md`: decision run and T; packets built and refused; runs complete, pending and incomplete; GPU hours; the map
hash and its logged time; anything that went wrong.
