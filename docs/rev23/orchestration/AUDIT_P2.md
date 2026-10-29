# AUDIT_P2: the 3P monitor without the GPU (2026-10-29)

**Verdict: APPROVED after one change of mine.**
- **Code:** `scratch/rev23/m3p/m3p_monitor.py` (about 1,280 lines), with 83 tests (network blocked in every test).
- **Build:** a Claude builder subagent wrote it, against WO_P2.
- **Not yet exercised:** the online SEC and SearXNG functions have run only on fakes. WO_P3 runs them live.

## What I checked

- I read the decision logic in full: `members`, `parse_submissions` (refuses another CIK's feed), `collected`,
  `filing_level`, `priority_for`, `price_signal`, `build_triggers` and Q1.
  - Each matches SPEC_m3p §§1–3 or a recorded open choice.
  - A 0.0 close is a value.
  - Operator-excluded names are never members.
- **Tests:** I reran them: 83 passed. The builder also broke six lines one at a time, and each break failed a test.

## Change made in this audit: Q1 has one owner

The monitor carried its own copy of Q1. That copy accepted "February 24 2026" without the comma, but the engine
(`m3o_engine.q1`, per PREREG "Month D, YYYY") does not. Two copies of one rule had already drifted apart.

The fix:
- `q1_verdict` now calls `m3o_engine.q1`. The local date parser and the orphaned window constant are removed.
- 83 tests still pass.
- The 3O engine is the single owner of Q1 (non-negotiable 5, in spirit).

## A defect it found in my code: `os.kill(pid, 0)` on Windows

On Windows this call **terminates** the process; it does not probe it. My runners `m3n/n5_run.py` and
`m3o_run/o2_run.py` used it in `take_lock`.

- **Why the risk was small:** IgnoreNew keeps the scheduled task from starting a second copy while one runs, so the
  check ran only when the task started anew. If the dead holder's pid had been reused, an unrelated process would have
  been killed.
- **The fix:** both runners now use `pid_alive` (OpenProcess + GetExitCodeProcess), copied from the monitor.
  - Checked: it reports the live DEV runner (pid 29840) as alive without harming it, itself as alive, and a dead pid
    as dead.
  - The running DEV process is unaffected; the change applies from its next launch.

## Rulings on the open choices (RR_P2)

1. **News queues nothing in v1:** accepted. News is gathered, deduplicated, labelled secondary and journaled, and it
   cannot act. Revisit after the first live week (WO_P3).
2. **A name not held: critical is P1; earnings and periodic filings are P3:** accepted.
3. **Form classes:** accepted. Any other 8-K is P3; an amendment is P3; 20-F and 40-F count as annual; `NT ` is any NT
   notice.
4. **News dedupe on title OR URL:** accepted.
5. **The later acceptance reading:** accepted. It is the same rule as the packet and the engine.
6. **A run key registers only on a complete, verified run:** accepted.
7. **Escalations are not auto-queued:** accepted. A rerun on the same evidence would hit the run key, so the name is
   `pending_review` until new evidence triggers a run. SPEC_m3o §3.2's "queued for 3P reanalysis" is read this way.
8. **Price trigger** (≥ at both boundaries, once per move, always P3): accepted. These are design values.

## Carried to WO_P3

- A wired price source and the command line.
- The scheduled task.
- Packet building.
- The `read_ledger` crash scan.
- `members()` reading the 3O ledger files.
- The SPEC §7 measures: missed events, false alarms, delay, throughput.
- The first live run of the SEC and SearXNG functions, paced as in B2.
