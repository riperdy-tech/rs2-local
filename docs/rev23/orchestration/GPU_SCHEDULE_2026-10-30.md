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
