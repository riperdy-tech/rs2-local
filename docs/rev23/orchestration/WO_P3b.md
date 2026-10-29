# WO_P3b: 3P model runs, throughput and the first live week (Claude executes; GPU)

**When:** after WO_O2 (the 10-30 formation's analyses). The monitored set's prior thesis runs are those formation runs,
in `wt-m3o/cache/m3m`.

**Code:**
- `scratch/rev23/m3p/m3p_monitor.py` (AUDIT_P3a);
- qwen_c at `4bc9425` in `wt-m3o`.

A monitoring run is `python -m qwen_c.runner <packet> --tasks material_events,thesis_change` (P0–P3), or all tasks
(P4). Its packet is built in the `verified` regime at the trigger's effective time.

## Steps

1. **The executor** `m3p_monitor.py run [--limit N]`:
   - It takes the queue's top entry and builds its packet (the newest verified screener commit at or before the
     trigger time, and the trigger's effective time as T).
   - It runs qwen_c in `wt-m3o` and calls `resolve(run_dir)`.
   - The run key blocks a duplicate run.
   - One instance at a time, using `pid_alive`.
   - Claude writes it, with tests on stub runs, before any GPU use.
2. **Smoke:** one real P2 or P3 entry (MA's earnings 8-K, from the 10-29 live pass, if still queued). Check that the
   `thesis_change` prior is the 10-30 formation run of that name (`find_prior`), and that the journal lines are
   complete.
3. **Throughput benchmark:** 10 runs of each task set (`material_events,thesis_change`; all tasks), timed from manifest
   start to `finished_at`. Report the median, p90 and max, and the GPU hours per day the §3 cadence needs.
4. **First live week:** register the gather task (`register_gather_task.ps1`) and an executor task in the same way, for
   seven days.
   - Measure coverage, queue age, reanalysis delay, false-trigger rate and crashes (SPEC_m3p §7).
   - Run the failure tests live: Ollama down, a killed run, a duplicate trigger.
5. **Missed-event review:** at the end of the week, search EDGAR independently for the monitored names' critical 8-K
   items and NT filings. Was each one caught, and when?

## Limits

- Paper only. Nothing in 3P sells, buys or writes `rn_depth`, the overlay or KIS.
- GPU standing go and the gaming rule: wait when the card is held.
- Both tasks are removed at the end of the week unless the operator keeps them, because they are standing
  configuration.
