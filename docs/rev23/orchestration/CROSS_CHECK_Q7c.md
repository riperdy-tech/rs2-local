# CROSS_CHECK_Q7c: third blind check of the Q7b fixes (2026-10-31 04:55Z)

**Reviewer:** a fresh Opus, blind. **Verdict: APPROVED WITH CONDITIONS.**

Q7b's blocking item holds. o2_requeue now restarts from every interruption point I could produce, and at each point the formation and
retrospective runners behave correctly. Q7b findings 2-16 hold, except 4, which holds only in part, and 10, which stays carried. What is
left:
- **A second o2_requeue launched while one is running resets the new map.** If a formation pass runs between the two instances, completed
  T2 runs are run again (finding 1). This is a condition before the Sunday re-queue: a three-line fix, or a strict one-launch procedure.
- **A kill between the two renames leaves the old finished flag in place.** The rerun reports success, but the formation task never starts
  (finding 2). The post-run check in condition C2 catches it.
- **A checks exception in attempt 1 still fills the slot when attempt 2 ends with another status** (finding 5). Fix before E3 step 3.

Everything else is minor and can be carried.

**Scope:** `m3o_run/` o2_requeue, o2_run (formation_waiting, the finished-flag test), o2_decide and o2_packets (now called in-process),
launch_o2.vbs and launch_o3.vbs; `m3q_e3/` e3_run, e3_freeze, e3_panel, snap_anchors and run_e3.cmd. Context read:
- wt-m3q `qwen_c/value/{run,checks,coe,inputs,desk}.py`, `qwen_c/runner.py`, `tools/audit_202608/ollama_raw.py` and `rs2_data.py`;
- wt-m3o `qwen_c/packet.py` (save);
- `m3l_forward/forward_ledger.py`, `terminal_d2/census_1a.py` and MRI's `duckdb_store.export_parquet`;
- WO_Q7, WO_O2, CROSS_CHECK_Q7 and Q7b, the rulings, and LOG 10-31.

I diffed every script against the copies Q7b simulated (`q7b/r_normal/`). The changes match the Q7b rulings line for line, and nothing else
changed: o2_decide and o2_packets are unchanged since 10-29, and the only change to o2_run is formation_waiting.

**What I ran.** Everything is under
`<session scratchpad>/q7c\`.
- **(a) The re-queue.** Copies of the four o2 scripts went into isolated trees (`setup_o2.py`). o2_run's `ollama_up` line was the only one
  patched. The stubs:
  - forward_ledger reads `decision.json`;
  - the packet builder writes deterministic bytes, refuses other bytes the way `packet.py:1062-1065` does, and can kill its parent or its
    whole process tree;
  - the qwen_c runner logs every run with its ticker and T, and can answer gpu_busy.

  `driver_rq.py` runs `o2_requeue.main()` exactly as `python o2_requeue.py 2026-10-30` does. At a chosen point it either kills
  (`os._exit`, so no `finally` runs and the lock keeps the dead pid) or pauses. After each point I ran the formation task (launch_o2.vbs's
  flag check, then o2_run), the retrospective task (launch_o3.vbs's check, then `o2_run --wt` on a `label: retrospective` map), a rerun, and
  then both tasks until they were idle (`sim_rq.py`).
- **(b) E3 results.** Copies of the e3 scripts and run_e3.cmd, with a **git-initialised** stub wt-m3q (`setup_e3.py`). The real HEAD and
  clean-tree preflight runs against it, and the stub run.py computes `versions.git` the way `runner.git_state` does. The stub writes every
  result shape run.py can write (`sim_e3c.py`, `cmd_bom.py`).
- **(c) The tools.** e3_panel.main() on fake inputs (`sim_panel.py`). anchor_set, census_rows, snap_anchors and formation_waiting with their
  module constants patched (`sim_c.py`).
- **Read-only checks:**
  - wt-m3q is at 8d25d85, clean, and no file changed in the last 90 min;
  - the six existing `cache/m3q/runs/*/result.json` have the shapes that judge() expects;
  - `stocks.json` and `factor_scores.json` at 02555c03, read through git (counts only);
  - `rs2_data.coe_loading` for every sector, on the pinned copy, read through `MRI_ANCHORS_DIR`;
  - metadata of the tasks, the processes and MRI's parquet. pid 10544 still runs the T1 batch: DEA at 04:51Z.
- **Two Windows tests:** `replace_test`, and `duck_test` (duckdb 1.5.3).

None of this touched the GPU, Ollama, the real lock (never opened), m3o\inputs, the o2\ state files or any real packet builder. It did not
modify anchors_by_build, and it did not open stage2_sealed. I ran no pytest: no repository code changed, and the scratch scripts have no
tests.

---

## Findings

### 1. Material; a condition before the Sunday re-queue. A second o2_requeue moves the freshly built map aside and resets every name.

**Where:**
- `o2_requeue.py:58-70` compares the map's run with the decision before the lock wait.
- Under the lock, `:84-88` re-reads the map and moves it aside, but never compares it with the decision again.
- `:102` calls `pre.unlink()` without `missing_ok`.

**Measured:**
- **`q7c/D_double_launch`.** Instance B held the lock. Instance C started, found the T1 map and waited.
  - B finished normally.
  - C then moved B's new T2 map aside as `formation_2026-10-30_superseded_41200000000.json`, so the map was superseded by its own run.
  - C wrote a fresh map and crashed at `pre.unlink` with FileNotFoundError (rc 1).
- **`q7c/D2_double_launch_gpu`.** Between B and C, the formation task ran AAA and BBB on B's map, then exited on gpu_busy.
  - C took the lock and reset the map.
  - The formation runner then ran all six names: **AAA 2 runs, BBB 2 runs at T2.**
  - The first two runs are recorded only in the self-superseded file.

**Scenario:** a detached launch shows no output in the session, so a second launch looks harmless.
- If C gets the lock first after B, nothing is run twice. What remains is the odd file and a traceback.
- If the formation runner gets it first and then leaves early (gpu_busy while the operator games, or Ollama down) within C's 4-hour wait,
  C resets the map. The completed T2 names are run again, and every name restarts its roughly 15 hours.

**Fix:**
- After `take_lock`, rerun `decision_for` and `check_file`.
- If the map's run_id already equals the decision, skip the move and continue as a resume.
- Use `pre.unlink(missing_ok=True)`.

Interim: before launching, check that no process has `o2_requeue` on its command line
(`Get-CimInstance Win32_Process -Filter "Name='python.exe'"`), and launch it once.

### 2. Minor. Silent, but the C2 post-run check catches it. Killed between the two renames, the old finished flag survives, and the T2 batch never starts.

**Where:**
- `o2_requeue.py:88-91` makes two separate renames: the map, then `finished_<T>.flag`.
- The resume path (`:93-95`) never looks at the flag.
- `launch_o2.vbs:8` quits while the flag exists.

**Measured (`q7c/A3_between_renames`):** after the rerun:
- the map is 41200000000 with `to_run 6`, preempt.flag is gone, and the summary looks normal;
- the T1 `finished_2026-10-30.flag` is still there;
- the formation task quit twice ("finished flag present"), and the retrospective runner yields on "formation_2026-10-30.json has work
  left";
- there were 0 T2 runs.

**Scenario:** the window is two consecutive system calls. Nothing in the script, and nothing in the stated procedure, would notice. The
names would reach the open as `to_run`, and O3 would yield forever.

**Fix:** before `:102`, if `finished_<T>.flag` exists while the map has `to_run` or `pending` names, move it aside under a free name. Or
apply condition C2.

### 3. Minor. Three restart paths need a second rerun or a step by hand. Nothing is lost in any of them.

- **(a) The decision moves during the lock wait** to a run with no check_new_runs record yet (`q7c/X_decide_moves`).
  - The map is moved aside first. Then o2_decide stops: "no check_new_runs record verifies fff999fff".
  - The formation task then crashes with FileNotFoundError every 15 min, which is harmless.
  - After check_new_runs, a rerun converged on the new run.
  - Fix: the same re-check under the lock as in finding 1.
- **(b) A second re-queue**, from T2 to T3 after a completed T1-to-T2 re-queue, killed after the move (`q7c/Z_second_requeue`). The rerun
  stops with "no formation_2026-10-30.json and 2 superseded maps; recover by hand" (`o2_requeue.py:71-72`).
  - This is plausible on Sunday, since the 10:00Z, 10:35Z and 12:35Z runs all score.
  - Fix: resume on one or more superseded maps. o2_decide re-derives the decision anyway.
- **(c) Resuming an older interrupted re-queue stops at that older run** (`q7c/R_resume_then_newer`). With T2 interrupted and the
  decision moved on to T3:
  - rerun 1 finishes T2's packets and prints `"run": "41200000000"`;
  - rerun 2 moves the map on to T3.
  - Fix: after a resume, go back to the decision comparison.

### 4. Minor. A rerun can time out behind the formation runner it let in.

**Where:** `o2_requeue.py:33, 77-79`.

**Measured (`q7c/W_wait_expiry`, WAIT_S shortened to 3 s):**
- The requeue was killed after 4 of 6 packets.
- The formation task took the stale lock and ran the 4 built names.
- A rerun started meanwhile stopped: "the runner lock was not free within WAIT_S".
- A second rerun, after that pass, built the last two packets. Nothing was run twice.

**Scenario:** for real, that formation pass over the built names can last up to about 57 × 16 min, roughly 15 h, against WAIT_S of 4 h.
The unbuilt names then wait for a later rerun by hand.

**Fix:** do not apply WAIT_S when resuming, since the lock holder is the formation itself. Or have the contemporaneous runner yield while
preempt.flag exists and its map has `to_build` names.

### 5. Material; fix before E3 step 3. A checks exception in attempt 1 is not seen if attempt 2 ends with another status.

**Where:**
- `e3_run.py:143-145` tests only when the final status is `invalid`, and only `body["checks"]["failures"]`.
- `run.py:147-151` takes the status from the last attempt and the checks from the last checked attempt.
- `run.py:137-138` sends attempt 1's failure text to the model as the repair message.

**Measured (`q7c/E_exc_attempt1_then_ok`, `..._then_malformed`, `..._then_overflow`):**
- Attempt 1 was `invalid` with "TypeError: unsupported operand", "KeyError: 'oi0'" or "AttributeError: x".
- Attempt 2 was ok, malformed or context_overflow.
- **All three filled.** In the malformed and overflow cases, the result's own `checks.failures` still held the exception.

**Scenario:** a gap in shape() lets a model value through, and that value raises an error in `_check`. The model is shown a Python
traceback as its "failure", then gets a second roll that avoids that path. The defect stays hidden, and the B6 counts include a repair
turn the model should not have had.

**Fix:** stop if any entry of `body["attempts"][i]["checks"]["failures"]` begins with one of the six names. Q7b 4's text said "any
attempt's"; the ruling narrowed it to the final `invalid`.

Measured as expected: a `DeskRefusal: ...` failure (`desk.py:21` subclasses ValueError) fills as `invalid`. That is right, because
checks.py catches every desk refusal of model inputs at `:535, 576, 595, 801, 814`.

### 6. Minor. A pin that changes during a valuation still fills that slot.

**Where:** `e3_run.py:197-199` checks the anchor copy and the closure before the run. `:228-230` fills without checking them again.

**Measured (`q7c/E_midpass_anchor`, `E_midpass_closure`):**
- A byte was added to the anchor file, or to the closure, while AAA 1000 ran.
- AAA 1000 filled `ok`.
- Then: "STOP: anchor cost_of_capital_anchor.json does not recompute" (exit 1, no STOP flag, and every later pass stops in preflight).

**Scenario:** the monthly `reference_closure.py --build` runs during E3. A rebuild dated after T is still refused by coe's own date check,
so a leak needs a rebuild dated on or before T. RR_Q7's comparison by value (ruling 10) would also catch it.

**Fix:** call `pinned_ok(d)` again after the run. If it fails, move the directory aside and stop.

### 7. Minor (latent). A name's own unmapped sector stops the whole batch.

**Where:**
- `e3_run.py:43, 141-142` treat every `coe_unavailable` as the environment.
- `coe.py:38, 42-44` also raise it when the loading is missing.
- `rs2_data.py:1184-1186` reports `unmapped_sector` for "Unknown".

**Measured:**
- In `stocks.json` at 02555c03, 260 rows have the sector "Unknown", which has no loading. 135 rows have "", which `e3_run.py:188` already
  turns into `panel_field_missing`.
- At T1, none of the 60 research_now names and none of the 103 watchlist names is either (counts only).

**Scenario:** the T2 book or draw picks up an "Unknown" name. Its first valuation writes STOP, and the batch idles until a human hand-edits
a run.

**Fix:** before the run, make a sector for which `rs2_data.mri_sector_id` returns None a named no_call. Or have judge treat the detail
"missing ['loading']" as a cause belonging to the name.

### 8. Minor. The closure guard fires about 25 h earlier than the ruling says.

**Where:**
- `e3_run.py:107-110` puts the limit at asof + 45 days, 00:00 KST, which is 2026-11-17T15:00Z, and refuses from 14:00Z.
- `rs2_data.py:1308-1313` treats the closure as stale from asof + 46 days, 00:00 KST, which is 2026-11-18T15:00Z. That is the date the
  ruling gives.

**Measured:** a closure dated asof 2026-09-16 was refused at 10-31T04:5xZ. rs2_data would accept it until 10-31T15:00Z.

The guard errs on the safe side. It matters only if E3 slips to 11-17.

**Fix:** use 46 days, or correct the ruling's text.

### 9. Minor. e3_freeze prints the hash exactly as it was typed.

**Where:** `e3_freeze.py:80`.

**Measured (`q7c/E_freeze`):** an argument with a BOM passes the check at `:46` (the non-hex filter), then crashes `print` with
UnicodeEncodeError on a cp1252 console. With PYTHONIOENCODING set to utf-8, the BOM or a CR would land inside the witness line instead.

**Fix:** print the filtered hash.

### 10. Minor. Any process reading the live map can crash the formation runner's save.

**Where:** `o2_run.py:91-94` has no retry. `o2_requeue.py:49, 58-59` read the map before taking the lock.

**Measured (`q7c/replace_test`):**
- While another process holds the file open, `os.replace` onto it fails with WinError 5. That is true for both Python `open()` and .NET
  `FileShare.ReadWrite`.
- o2_run then raises before it records the finished run, so the next pass runs that name again.

**Exposure:**
- o2_requeue's two reads before the lock, about 2e-6 per launch;
- any monitoring read of the live map during a batch.

formation_waiting reads maps only while it holds the lock, so it adds no exposure.

**Fix:**
- Retry `os.replace` a few times, for example 10 × 0.2 s, in `o2_run.save`, and in `e3_run.save` the same way.
- Monitor through `runner.out`.

### 11. Note on the carried Q7b 10. The bill-rate read can also make MRI's daily export fail.

**Where:** `run.py:46` reads MRI's live `raw_observations.parquet` once per operating or commodity valuation.
`duckdb_store.export_parquet` rewrites it every day at about 21:34Z (last written 06:34:37 KST; 0.9 MB).

**Measured (`q7c/duck_test`):** 3 of 20 `COPY ... TO` calls failed with "IO Error: Could not move file: Access is denied" while a DuckDB
reader looped over the file.

The risk per day is very small. A read takes about 10-30 ms, and reads come roughly every 10 min.

**Fix (optional):** e3_run starts no valuation between 21:20Z and 21:50Z.

### 12. Condition (procedure). The formation task must still be registered after the re-queue.

o2_requeue only sets the flag aside. The T2 names run only if RS2-M3O-Formation-Runner fires. WO_O2 step 7 says to remove that task "when
the batch is done". If it is removed after the T1 batch on Saturday, nothing runs T2, and no script notices.

### 13. Trivial. The e3_panel docstring still says "so the seal stays closed".

At `e3_panel.py:9-10`, against ruling 9's "unvalued". WO_Q7:21-24 is already correct.

---

## Q7b finding → holds / does not hold

| Q7b | Ruled fix | Holds? | Evidence; what remains |
|---|---|---|---|
| 1 | Re-queue resumable, in-process, flag cleared only when nothing is to_build, launched detached | **Holds** | Killed in the lock wait, after the move, after o2_decide, mid-packets (in-process, packet child surviving, whole tree), and before the preempt unlink: one rerun converges every time. The map is at the new run with no to_build, the T1 map and flag are set aside, preempt.flag is gone, and each T2 name runs exactly once (`A2`, `A4-A7`, `A6b`, `A6c`). Runners at each point: if the map is missing, the formation task crashes harmlessly and releases the lock. With every name to_build it runs nothing and writes no flag. With some names to_run it runs only those. The retrospective runner yields (exit 5). While o2_requeue is alive, both runners get "another runner holds the lock" (`P_*`). The surviving packet child's packet is a same-bytes no-op on rebuild; packet.py has no timestamp, only `--T now` (`:1094`). Remaining: findings 1-4 |
| 2 | `check_file` before touching anything | **Holds** | No record: "STOP: no check_new_runs record verifies fff999", nothing touched. A verifier error stops the same way (`A1`). Remaining: the decision can still move during the lock wait (3a) |
| 3 | Environment no_calls stop; pins rechecked before each valuation; date guard | **Holds** | `coe_unavailable` and `coe_anchor_after_T` each write STOP at once and move the directory aside. Anchors, closure and packet are checked before every valuation. The guard refuses. Remaining: a change during a valuation (6); the guard fires 25 h early (8); a name's unmapped sector also stops the batch (7) |
| 4 | Checks exception → STOP | **Partly** | A final `invalid` with KeyError stops. An exception in attempt 1 followed by ok, malformed or context_overflow fills (5) |
| 5 | HEAD and a clean tree before a pass; fill-time git, packet, ticker, seed and T | **Holds** | A dirty tree, `[None, None]`, another packet, ticker, seed or T: each one stops. A real untracked file written during a run makes the tree dirty and stops the batch (`E_dirty_real`). Before a pass, an untracked file and a moved HEAD are refused |
| 6 | Read from the definition; top-level fields and names compared | **Holds** | run.py received the definition's `MRI_ANCHORS_DIR`. An edit to the anchors dir, to a name field, or the removal of a name is refused. `failures` and `orphans` keys are allowed |
| 7 | e3_freeze makes the same comparisons and refuses on STOP | **Holds** | It refuses on STOP, an edited name, an edited top-level field, a changed result, an unfilled slot and a held lock, and the clean case writes the witness line. Remaining: the hash is printed raw (9) |
| 8 | Orphan guard; first free suffix | **Holds** | `_orphan1` already existed, so the directory became `_orphan2`. It was recorded and its result.json kept (`E_orphan`). Attempts number from 1 to 3 |
| 9 | Wording: "unvalued" | **Holds** in WO_Q7 | The e3_panel docstring is stale (13). In `sim_panel` the sealed names are dropped and only counted |
| 10 | Bill rate carried; RR_Q7 compares coe legs by value | Carried | RR_Q7 not written yet. Also 11 |
| 11 | Regex filter, print of the cause, WAIT_S 4 h | **Holds** | Frozen, superseded, `.T1backup`, `.tmp` and retrospective maps are skipped. An unreadable live map, to_build names, a later live map and preempt.flag each yield and print why. Remaining: 4 |
| 12 | Non-hex characters stripped | **Holds** | Uppercase and BOM+CRLF are accepted by e3_run and e3_freeze. run_e3.cmd works with an ASCII file and with this machine's PowerShell `>` output (UTF-8 BOM). A UTF-16 file stops every pass, which is safe |
| 13 | Register E3 only after `finished_2026-09-30.flag` | **Holds** (written condition) | WO_Q7 step 3. RS2-M3Q-E3-Runner was absent at 04:22Z. The Q7-9 lock condition still applies, and a killed re-queue now leaves its own pid in the lock as well |
| 14 | Market cap only on the operating and commodity routes | **Holds** | A financial name ran with `--market-cap 0`. An operating name with 0 gets `market_cap_unavailable` (`inputs.py:198-199`) |
| 15 | `cik_mismatch` no_call; census code commit | **Holds** | The FFF and W2 cases. `census_1a.py:21-23` imports from wt-v22 (e604cca, clean), the commit e3_panel records |
| 16 | anchor_set skips `.tmp` and `.stale`; snap moves a crashed `.tmp` aside | **Holds** | It picked the newest copy built at or before T over `.tmp`, `.stale1`, copies without a manifest and copies built after T. A tampered newest copy stops rather than falling back. A crash mid-copy leaves `.tmp`, and the next snap moves it to `.stale1`, or to `.stale2` when `.stale1` already exists (`sim_c`) |

## Fix list

| # | Item | Status | Owner |
|---|---|---|---|
| C1 = 1 | Recheck the decision and `check_file` under the lock, skip the move if it was already applied, `missing_ok`. Or check that no o2_requeue process exists and launch once | **condition: before the Sunday re-queue** | coordinator (Claude) |
| C2 = 2, 12 | After the re-queue: preempt.flag gone; no `to_build`; `run_id` is the decision's; `finished_2026-10-30.flag` absent while any name is to_run; RS2-M3O-Formation-Runner registered; `runner.out` shows T2 names starting | **condition: at the Sunday re-queue** | coordinator |
| C3 = 5 | Scan every attempt for checks exceptions | **condition: before E3 step 3** | coordinator |
| 3, 4 | Resume on one or more superseded maps; go back to the decision after a resume; no WAIT_S deadline on resume | carriable (each recovers by rerun) | coordinator |
| 6, 7, 8, 9 | Recheck the pins after the run; name-level no_call for an unmapped sector; 46 days or the ruling text; print the filtered hash | carriable; 6 and 7 preferably before step 3 | coordinator |
| 10, 11, 13 | Retry `os.replace`; monitor through runner.out; optional MRI-export quiet window; docstring | carriable | coordinator |

**Verdict: APPROVED WITH CONDITIONS.** The re-queue may run on Sunday once C1 is in place. C2 is checked when it finishes, and C3 is done
before E3 step 3. The rest can be carried.
