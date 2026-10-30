# GPU schedule, 2026-10-30 to 11-02 (planning note, Claude)

All runs go through scheduled tasks outside Claude, and each starts with a smoke run. The GPU standing go and the
gaming rule apply: a run waits when the card is held.

| When (KST) | Run | Prerequisite | Est. |
|---|---|---|---|
| 10-29 to ~10-30 02:00 | **3N DEV** (running, RS2-M3N-DEV-Runner) | — | — |
| 10-30 ~02:00–08:00 | Score DEV: final adjudication, `n6_score`, `n6_tables`, `n6_taxonomy`; RR_N_DEV §5–8; remove the DEV task | the DEV finished flag | no GPU |
| 10-30 day | **§7 fixes:** v7 (done) plus any prompt or contract fix the taxonomy calls for, each versioned, with tests. If the prompt changes, its PREREG note is written before any FRESH packet is read. | RR_N_DEV | no GPU |
| 10-30 day, after the fixes | **DEV regression rerun** on the final version (`n7_run.py --packets n7/packets_v7.jsonl --wt ../wt-m3n-v6 --out n7/runs_dev_v7.jsonl`). The packets are rebuilt if the builder changes again. | the fixes committed | ~6 h |
| 10-30 22:30 KST (LESL T2 13:30Z) and later | **FRESH:** unseal, refresh the frame tip, build the FRESH packets, run once (`n7_run.py`, its own output file) | the regression run finished; LESL T2 passed | ~6 h |
| 10-31 ~10:00 KST onward | **WO_O2:** the 10-30 formation. Decide after the Friday price-refresh run (~01:00Z), then packets (~8 min), smoke, run | the verifier PASS | 16–19 h, done before 11-02 23:30 KST |
| after WO_O2 | **WO_P3b:** the monitoring executor, benchmark and live week; **WO_O3:** the 09-30 retrospective | — | — |

**Conflict rule:** WO_O2 is time-critical (forward evidence), so it pre-empts FRESH. If FRESH has not finished by
10-31 10:00 KST, it pauses (stopped between runs; the runner resumes) and continues after WO_O2.

## Rev b (2026-10-30 16:00 KST): the GPU calendar to 11-10

**Order rules:**
- WO_O2 formation runs pre-empt everything (the fill opens 11-02 14:30Z).
- 3P's executor never runs while a formation runs on the same run root.
- Every long run gets a smoke turn first.
- The gaming rule applies throughout: wait whenever the card is held.

| When (KST) | GPU | CPU alongside |
|---|---|---|
| 10-30 ~17:15 | DEV regression ends; remove `RS2-M3N-DEVREG-Runner`; **3Q DAR smoke** (one run, mechanics only, ~10 min) | score the regression (the rulings are done) |
| 10-30 22:30 → | **FRESH**: unseal, build packets (CPU, SEC), smoke one task, then register `RS2-M3N-FRESH-Runner`. About 212 tasks, ~9–10 h, overnight | — |
| 10-31 ~10:00 | After the 10-30 price refresh (~01:00Z): **WO_O2** decide, packets, smoke. If FRESH is still running, its lock is respected; the formation task starts when FRESH's current task ends. FRESH resumes after the formation (it is resumable) | score FRESH if finished; draft CLOSE_3N |
| 10-31 → 11-02 | **WO_O2 formation runs** (~60 names × 16–19 min ≈ 16–19 h) | WO_Q6 build (financial route), then its blind review; 3S report scaffolding |
| 11-02 before 23:30 | Freeze the formation map; push the GitHub witness | forward_ledger, the universe fetch and m3o_engine after the fill |
| 11-03 | **3Q E3**: value the 10-30 formation names on the price-blind prompt (~2 runs × ~50 callable × ~6 min ≈ 10 h); hash and witness the results before any outcome | E3 blind readers (fresh Opus, inputs masked) once the runs are frozen |
| 11-04 → 11-10 | **WO_P3b**: smoke, throughput benchmark, then the 7-day live week (gather + executor tasks) | the missed-event review at week end |

**Risks:**
- FRESH overrunning into the formation window. The formation wins, and FRESH waits.
- A failed formation smoke. That stops the batch, by rule.
- E3 must not start before the formation map is frozen, because its names come from it.
