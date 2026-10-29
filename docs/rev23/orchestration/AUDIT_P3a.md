# AUDIT_P3a: the 3P monitor wired to real inputs (2026-10-29)

**Verdict: APPROVED.** `m3p_monitor.py` is now 1,598 lines. The tests went from 83 to **119 passed** (rerun by me), and
the builder broke seven lines one at a time, each caught by a test.

## Checked

- **The SEC contact** is read from `SEC_USER_AGENT` at call time and refused if it is missing or has no email
  (`m3p_monitor.py:251-254`).
  - The builder found it unset in its process but set in the operator's Windows user environment. It passed that value
    without printing it, which is what the scheduled task will see.
  - The value is a name and an email that SEC requires, not a secret or a `.env` file. I accept the live state it wrote.
- **`os.kill`** remains only in the non-Windows branch of `pid_alive` (line 730).
- **The monitored set** comes from the `m3l_forward` fallback (the 2026-09-30 formation) until the 3O ledger exists, and
  `cik_map.json` is read through `git show` at the formation's commit.
  - The live pass had 58 members: 60 less SENEA and SENEB.
- **The live pass** (AMD, MA, MU, KSS, HOG): SEC, SearXNG and Yahoo all answered, and 130 closes were kept per name.
  - Queue: HOG P1 (an 8-K with 2.02, 5.02 and 9.01, and a C2+C7 baseline-B hit), MA P3 (an earnings 8-K), and the
    others P4.
  - The HOG hit is a baseline-B pattern on an earnings release. It is a trigger to read, not an event. The model reads
    it in WO_P3b, and the result goes to the journal.
- **The run root** in `run_gather.cmd` (`..\wt-m3o\cache\m3m`) is correct: qwen_c writes `ROOT/cache/m3m/runs` and its
  ledger there (`runner.py:81`), and wt-m3o is the formation worktree (WO_O2).

## Rulings on the open choices (RR_P3a)

All are accepted:
- the company name taken from the SEC submissions feed;
- a shared CIK (AFGB…AFGE) gathered once and the others marked `shared_cik`;
- the crash scan skipping runs younger than 6 hours;
- a crashed run re-queued at P2 with one retry.

## Carried to WO_P3b

- Register the task (`register_gather_task.ps1`) only together with the model runs. The registrar has not been run.
- The SPEC §7 measures.
- The first crash scan on real data.
