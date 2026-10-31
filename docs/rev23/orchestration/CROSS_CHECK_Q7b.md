# CROSS_CHECK_Q7b: blind re-check of the CROSS_CHECK_Q7 fixes (2026-10-31 04:15Z)

**Reviewer:** a fresh Opus, blind. **Verdict: APPROVED WITH CONDITIONS.**

The four Q7 blocking fixes hold on their main paths. I measured each one below. What is left:
- o2_requeue cannot be restarted. If it is interrupted, the formation stalls or loses runs. This blocks the Sunday re-queue.
- e3_run still fills a slot in three cases where it should stop:
  - a no_call caused by the environment;
  - an exception inside the checks;
  - a result from dirty code or another packet.
- The definition check covers only the names. e3_freeze does not check the names at all.
- The Stage-2 seal can be opened by set difference.

None of this needs a redesign. Every condition is tied to a named step.

**Scope:** `m3q_e3/` (e3_panel, e3_run, e3_freeze, snap_anchors, run_e3.cmd, launch_e3.vbs, register_e3_task.ps1, launch_snap.vbs,
register_snap_task.ps1), and `m3o_run/` (o2_run, o2_requeue, o2_decide, o2_packets, run_o3.cmd, launch_o3.vbs). Context read: wt-m3q
`qwen_c/value/{run,coe,checks,inputs,facts}.py`, `qwen_c/runner.py`, `qwen_c/sec_store.py`, wt-m3q `paths.py` and `rs2_data.py` (the
valuation imports the worktree's copies, cwd wt-m3q; rs2_data is identical to rs2-local's, paths.py differs only by three newer keys),
`terminal_d2/census_1a{,_addendum}.py`, wt-v22 `valuation/classification.py`, `m3l_forward/forward_ledger.py`, `m3o/m3o_engine.py`,
WO_Q7, WO_O2, CROSS_CHECK_Q7, its rulings, SPEC_m3q §0/§5/§6/§8, RR_Q1 §5, LOG 10-31.

**What I ran.** All of it was read-only on everything real.
- In wt-m3q, `from qwen_c import runner; print(runner.llm_provider.OLLAMA_URL)`, as an import only (no HTTP), and `python paths.py`.
- `coe.cost_of_equity` with `MRI_ANCHORS_DIR` set to the pinned copy, at T1, at a Sunday T and at two earlier T. I also ran it with a
  faked wall clock.
- `rs2_data.coe_loading` for every sector in the panel.
- Simulations on copies of the current scripts, with stubs for run.py, the GPU probe, the packet builder, the qwen_c runner and
  forward_ledger. In the o2_run copy, `ollama_up` was stubbed. Everything ran under
  `<session scratchpad>/q7b\`
  (`setup_sim.py`, `sim_e3.py`, `sim_o2.py`, `coe_probe.py`).
- Read-only queries:
  - the three scheduled tasks;
  - the persistent environment (STOCKS_ROOT is set at user level, so the tasks inherit it);
  - the git state of wt-m3q (8d25d85, clean) and wt-v22 (e604cca, clean);
  - the market caps in stocks.json at 02555c03;
  - the structure of the sealed file (3 ticker strings). I did not read the names, and the complement check below is counts only.

Nothing touched the GPU, Ollama, the live lock (it still holds 10544; runner.out has reached CHA), m3o/inputs, the real
anchors_by_build, or any real script. No pytest was run: no repository code changed, and the scratch scripts have no tests.

---

## Findings

### 1. Blocking before the Sunday re-queue. An interrupted o2_requeue cannot be restarted. The formation stalls or loses runs, and `preempt.flag` is never cleared.

**Where:**
- `o2_requeue.py:36-42`: a rerun reads the new map and returns "unchanged".
- `o2_requeue.py:61-64`: o2_decide and o2_packets run as child processes, but the lock holds o2_requeue's own pid.
- `o2_requeue.py:69`: preempt.flag is removed only on success.
- `o2_packets.py:27-49`: no lock check, and it rewrites the whole map at `:47`.
- `o2_run.py:71-72`: while the flag exists, O3 and E3 yield, with no expiry.

**Measured** (copies, a 6-name book, 1.5 s per packet; `q7b/r_kill_parent`, `q7b/r_kill_tree`):
- **(A) Only o2_requeue killed, 2 of 6 packets built.**
  - The lock kept the dead pid (10936), and o2_packets kept running without the lock.
  - The formation runner took the stale lock and completed AAA and BBB. o2_packets' later saves reset both to `to_run`. The next
    formation pass ran AAA and BBB a second time.
  - `preempt.flag` stayed. The retrospective runner still yielded (exit 5) after the formation had finished.
- **(B) The whole process tree killed at the same point.**
  - 4 names stayed `to_build`.
  - A rerun of o2_requeue printed "unchanged: the decision run is still 41200000000; nothing to re-queue" and exited 0.
  - The formation runner ran the 2 built names and wrote no finished flag. Nothing ever builds the other 4. The retrospective runner
    yields forever.

**Scenario:** any of these during the ~5 minutes of packet building (4 min 48 s at T1) or the lock wait of up to 40 minutes:
- a reboot;
- a closed or restarted Claude session;
- a tool timeout that kills the process.

Then:
- With (B), the unbuilt names reach the 11-02 open as `analysis_pending` (m3o_engine.py:321) with no alarm. That formation evidence
  is lost for good.
- With (A), names get two formation runs at the same T.
- In both cases E3 later yields forever, because the flag is never cleared.

**Fix:**
- A rerun resumes instead of printing "unchanged". It resumes when any of these holds:
  - preempt.flag exists;
  - the map has `to_build` names;
  - the map is missing and exactly one `formation_<T>_superseded_*.json` exists.

  It takes the lock, runs whatever step is left, and clears the flag only when no name is `to_build`.
- Call o2_decide and o2_packets in-process, or make o2_packets stop before each save unless the lock file holds its parent's pid and
  that pid is alive.
- Launch the re-queue detached, the way the runners are launched. After it ends, check four things:
  - the flag is gone;
  - no name is `to_build`;
  - the map's `run_id` is the new one;
  - the old finished flag has been set aside.

### 2. Minor. o2_requeue's pre-check leaves out o2_decide's own precondition, so Q7-12's case survives.

**Where:**
- `o2_requeue.py:37-42` checks only `FL.decision_for`.
- `o2_decide.py:43-44` also requires a check_new_runs record with verdict PASS and pair PASS for the output commit.

**Measured** (`q7b/r_decide_stop`): the new run passed decision_for but had no such record.
- The map was moved aside, o2_decide stopped, and no `formation_2026-10-30.json` existed.
- The formation runner crashed with FileNotFoundError, and so did a rerun of o2_requeue.
- `preempt.flag` stayed.

Nothing is lost, but recovery is by hand.

**Fix:** call `o2_decide.check_file(res["output_commit"])` before writing preempt.flag, and stop with nothing touched if it returns
None.

### 3. Material; fix before the E3 smoke. A no_call caused by the environment fills its slot permanently.

**Where:**
- `e3_run.py:33, 138`: a no_call fills whatever its reason.
- `coe.py:36-49`.
- `rs2_data.py:1010` and `:1308-1313`: the age of the anchors and of the closure is measured against the wall clock, not against T.
- `e3_run.py:71-72`: the closure hash is checked once per pass, and a pass can last 15-20 h.

**Measured:**
- All 9 sectors in the dry panel have a loading in the pinned copy. So with the pinned set verified, `coe_unavailable` and
  `coe_anchor_after_T` can only come from the environment.
- I ran the pinned copy at a Sunday T with a faked clock:
  - 2026-11-18 23:59 KST: ok, r = 0.08782;
  - 2026-11-19 00:01 KST: `REFUSED coe_unavailable ... reference_closure_stale(2026-10-04, 46 days, limit 45)`;
  - 2026-12-15 00:01 KST: rf, g_anchor and the loading are refused as well.

**Scenario:** either of two things happens:
- E3 slips past 2026-11-18 15:00Z, for example because a STOP is left over a weekend;
- the closure is rebuilt during a pass.

Every remaining slot then fills as `no_call` in a single pass, and under "a run is never repeated" none of them can be redone.

**Fix:**
- Treat a no_call whose reason is `coe_unavailable` or `coe_anchor_after_T` as a stop: no fill, move the directory aside, write the
  STOP flag.
- Recompute the anchor and closure hashes before every valuation, not once per pass.
- Refuse to start a pass on or after 2026-11-18 (closure asof + 45 days).

### 4. Material; fix before the E3 smoke. An exception inside the checks fills its slot as `invalid`.

**Where:**
- `checks.py:311-319` turns six exception types, raised anywhere in `_check` or `_check_fin`, into status `invalid` with the exception
  text as the failure: KeyError, TypeError, ValueError, AttributeError, ZeroDivisionError and OverflowError.
- Only an AssertionError becomes `engine_defect` (`run.py:129-132`).
- `e3_run.py:33` fills `invalid`.

**Scenario:**
- A defect on one code path is raised for every name that takes that path, for example a missing key on the financial route for a
  filer that lacks one line.
- Each of those names fills as `invalid` in a single pass. B6 then counts them as model failures, and nobody sees the defect.

That is the case WO_Q7 step 3 means by "a code defect stops the batch". After `shape()` has passed, such an exception is either a code
defect or a model value that the shape check missed. Either way, a human should rule on it before the slot is spent.

**Fix:** in e3_run, if any attempt's `checks.failures` entry begins with one of those six exception names, do not fill. Move the
directory aside and write the STOP flag.

### 5. Material; fix before the E3 run (step 3). A result fills its slot unchecked, and the freeze then refuses a panel that can no longer be repaired.

**Where:**
- `e3_run.py:149-152` fills without reading `versions.git` or `packet_sha256`.
- `e3_freeze.py:68-71` checks both, but only at the end.

**Measured** (`q7b/e_dirty`): e3_run filled two bad results:
- one whose `versions.git` was `[8d25d85…, true]`;
- one with another packet's sha256.

e3_freeze then stopped: "BBB seed 1000 code state [..., True] is not the panel's clean ...".

**Scenario:** `runner.git_state` (`runner.py:147-155`) reads `git status --porcelain`, which counts untracked files. Any non-ignored
file written into wt-m3q during the batch makes every later result dirty. All of them fill, the freeze fails, and the panel is lost.

**Fix:**
- Before a pass, require HEAD to equal `code.git` and the tree to be clean.
- At fill time, require all of these, or else do not fill, move the directory aside and stop:
  - `versions.git == [code.git, false]`;
  - `packet_sha256` equals the panel's;
  - `ticker`, `seed` and `T` equal the slot's.

### 6. Material; fix before the E3 run. The definition check covers only the names. The anchors, the closure and the code commit are read from the editable panel.

**Where:**
- `e3_run.py:59-72` compares the names, then recomputes the hashes against `p["anchors"]` and `p["closure"]`.
- `e3_run.py:105` takes `MRI_ANCHORS_DIR` from the panel.
- `e3_freeze.py:47-52, 70, 73-75` do the same.

**Measured** (`q7b/e_def`):
- I pointed the panel's anchors at a later build that was internally consistent, and edited `code.git`.
  - e3_run ran both seeds, and run.py received `MRI_ANCHORS_DIR=…\20261101T213000`.
  - The definition still named `20261030T213449`, and its hash still recomputed.
- An edited name field was refused, as intended.

**Fix:** in both scripts, read anchors, closure, code, `decision_time_utc` and `map_sha256` from the definition. Or stop unless every
top-level field except `names` equals the definition's.

### 7. Material; fix before the freeze (step 4). e3_freeze never compares the panel's names with the definition.

**Where:** `e3_freeze.py:44-46` hashes the definition, but reads the names only from the panel (`:54`).

**Measured** (`q7b/e_freeze_names`): after the last pass I deleted one name and changed another's family.
- e3_freeze printed a witness line ending "names 2 ok 4".
- e3_run refused the same edit.

**Fix:**
- Add e3_run's names comparison and the top-level comparison from finding 6.
- Refuse while `e3/STOP_<T>.flag` exists, to meet the WO_Q7 acceptance test "no STOP flag left unresolved".

### 8. Minor; fix with 5. A run directory left by a killed pass is reused in place.

**Where:** `e3_run.py:130-136` never checks that the directory is absent. `run.py:96-97` creates it with `exist_ok=True`, then
overwrites `raw/attempt_N.json` and `result.json`.

**Measured** (`q7b/e_orphan`): a complete result.json that had never been recorded was overwritten, and no copy was kept.

**Scenario:** a reboot after run.py has written result.json but before e3_run has saved the panel, or a hand run of run.py. The slot is
valued twice and the first result is lost.

Also: after a human resets `failures`, `shutil.move` into an existing `_attempt<k>` puts the directory inside it instead of failing.

**Fix:** if the directory exists before a valuation, move it aside as `_orphan<k>` and record that, or stop.

### 9. Material; operator decision. The Stage-2 seal can be opened by set difference.

**Where:**
- `e3_panel.py:168, 172`: the panel's book is the map's book minus the held-out names.
- `:187-191`: the counts are recorded.
- `panel_2026-10-30.dry.json` is already on disk.

**Measured** (counts only; I neither computed nor read the names):
- The map's book has 60 names and the panel's book 56. Operator-excluded names in the book: 2. B5 holdouts in the book: 0.
- The residual is 2, which equals the panel's own count of sealed names in the book.
- So the frozen map minus the panel names exactly the 2 sealed book names.
- No script prints a sealed name.

A sealed watchlist name can be identified the same way whenever it ranks among the first DRAW positions after the other held-out
names. That is not the case at T1, where the 11th name was drawn.

**Fix:** the operator, as seal holder, chooses one of two rulings:
- a prospective T does not open the sealed names, so they stay in the panel;
- or their identity can be derived while their valuations stay unrun, and WO_Q7 and RR_Q7 say so instead of "the seal stays closed".

Until then, do not publish the panel's name list beside the map.

### 10. Minor. Two valuation inputs are outside the pin, and a result does not name its anchor copy.

- **The closure is not redirected by `MRI_ANCHORS_DIR`.**
  - `coe.closure_path()` (`coe.py:22-26`) reads rs2-local's main checkout through the git common directory. It resolves to
    `<stocks root>/rs2-local\cache\reference_closure.json`.
  - That is the same file as the panel's CLOSURE (sha256 `fdb3e7b7…`, asof 2026-10-04, built 10-04; no task rebuilds it).
  - It is pinned by hash only (see 3).
- **The bill rate is read live.**
  - `bill_rate_mean` (`run.py:46`; `rs2_data.py:1251-1283`) reads MRI's live `data/raw/fred/raw_observations.parquet`. MRI rewrites
    that file in place every day with `COPY … TO` (`duckdb_store.py:2611-2656`), and nothing copies or hashes it.
  - DTB3 over a past window does not change, so the value is stable in practice.
  - A read during the ~21:34Z export fails the slot, which the failure path handles.
  - A missing file silently drops the cash term (`inputs.py:132-134`, stamped).
- **A result records the anchors' asof and values, not which copy it used** (`coe.py:52-53`). WO_Q7 step 2's check of "the anchor copy
  in coe" can only be made by value.

**Fix:** e3_freeze compares each result's `coe.rf`, `g_anchor` and `closure_erp` with the pinned files. The panel records the
parquet's sha256 at draw time.

### 11. Minor. formation_waiting filters by a file-name pattern.

**Where:** `o2_run.py:73-84`.

**Measured** (`q7b/e_waiting`):
- Frozen, superseded and retrospective maps are skipped correctly.
- A hand copy named `formation_2026-10-30.T1backup.json` makes it return True indefinitely.

**Also:**
- The contemporaneous runner rightly ignores preempt.flag. So a re-queue that meets a live formation batch waits `WAIT_S` = 2400 s
  (`o2_requeue.py:30`) and then stops.
- A retrospective run can also last longer than 40 min: 8 tasks, each with `TASK_TIMEOUT_S` 1800.

The stop is safe, but the re-queue is time-critical.

**Fix:**
- Match `^formation_\d{4}-\d{2}-\d{2}\.json$`.
- Print the file that causes a yield.
- Let o2_requeue wait longer: the flag already guarantees a yield after the current run.

### 12. Minor. `run_e3.cmd:5` reads the hash with `set /p`, which keeps a BOM.

PowerShell 5.1's `>` and `Out-File` write a BOM. Every pass then stops with "does not recompute". The hand smoke in step 2 never goes
through this file.

**Fix:** write `e3\def_sha256_<T>.txt` as ASCII with no BOM, or have e3_run strip non-hex characters from `--def-sha256`.

### 13. Minor. The carried Q7-9 also affects E3.

E3 and O3 are both AtLogOn with StartWhenAvailable, so the non-atomic lock can let both in at logon or wake.

**Condition:** register E3 only after `finished_2026-09-30.flag` exists, or after the O_EXCL lock is in place.

### 14. Minor. `e3_run.py:119` treats a zero market cap as missing on every route.

- The financial route needs no market value (`run.py:62-73`).
- At 02555c03, 769 of the 7,020 rows in stocks.json have marketCap 0, and none is NaN.
- So a financial name with 0 loses its valuation, and an operating name gets `panel_field_missing` instead of
  `market_cap_unavailable`.

**Fix:** require the market cap only on the operating and commodity routes.

### 15. Minor. On a CIK mismatch the family still belongs to the census entity.

`e3_panel.py:215-217` records `census_cik`, but keeps the family measured on that CIK. The panel also does not record the census code
(wt-v22 e604cca) for census_measure rows.

**Fix:** on a mismatch, measure again on the packet's CIK, or make the name the named no_call `cik_mismatch`. Record the wt-v22 commit.

### 16. Minor. snap_anchors can leave a `.tmp` directory behind.

A crash between `snap_anchors.py:36` and `:40` leaves `<built>.tmp`. Every later snap of that build then crashes on `mkdir`, and
`anchor_set` (`e3_panel.py:125-130`) would pin a `.tmp` directory that holds a manifest.

**Fix:** skip `*.tmp` in anchor_set. Have the snap reuse a stale `.tmp`, or move it aside.

### 17. Reporting; carriable.

- **Consumed names:** the WO_Q7 list matches RR_Q1 §5's explicit lists (13 of 13 in the panel). It is not checked against the rev-24
  pilot six or the 3N DEV set, which were consumed for contract tuning just as the 3M live set was.
- **Definition witness:** before the smoke, the definition hash is recorded only in LOG.md, which is self-attested. A one-line push like
  the formation witness would make the acceptance test "logged before the smoke" independent. This was Q7-6's "preferably".

---

## Finding of Q7 → holds / does not hold

| Q7 | Ruled fix | Holds? | Evidence; what remains |
|---|---|---|---|
| 1 | Pinned anchor copy through `MRI_ANCHORS_DIR` | **Holds** for the anchors | The variable wins over config (`paths.py:101, 148-150`; wt-m3q config pins none). `rs2_data.anchors_dir/load_anchors` read the copy, and run.py received the panel's directory. coe passes at T1 (2026-10-31T01:03:43Z) and at a Sunday T (2026-11-01T11:00Z), r = 0.08782 (Industrials), legs asof 10-30, closure 10-04. A copy's asof is its build's UTC date, so a T2 panel pins the 10-31 build (asof 10-31 ≤ 11-01). coe alone would accept a copy built up to 21 h after T (it passed at T 10-30T20:00Z); anchor_set's `built_at ≤ T` is what prevents that. Remaining: the closure is pinned by hash once per pass, the pin expires 11-18, the bill rate is outside it (3, 10) |
| 2 | GPU probe import | **Holds** | `runner.llm_provider.OLLAMA_URL` = `http://127.0.0.1:11434/api/chat`. A probe crash exits 1 with "STOP: the GPU probe crashed", distinct from exit 3 |
| 3 | Only model or code outcomes fill; move aside; STOP on the third failure | **Holds** for the outcomes named | Simulated: the 6 fill statuses fill and write the finished flag. engine_defect, timeout, infra_retry, infra_fatal, exit 1, and exit 0 without result.json each give `_attempt<k>` and exit 6. The third failure gives STOP and exit 7, and the next pass returns 7 without taking the lock. Those are all the statuses run.py can write. Remaining: environment no_calls (3), exceptions as `invalid` (4), unchecked fills (5), orphan directories (8) |
| 4 | Re-queue holds the lock through decide and packets; `to_build` counts as unfinished | **Holds if it runs to the end**; **does not hold if interrupted** | `q7b/r_normal`: preempt set and then cleared, T1 map and flag set aside, T2 has 6 to_run, O3 yielded until the formation finished and then ran. Interrupted: (1) |
| 5 | B7 test for census_measure names; `financial_unconfirmed`; a not-built name never becomes financial | **Holds** | `e3_panel.py:80-88` follows WO_Q7. A financial family on a real-estate route cannot occur: the classifier makes SIC 6500-6599 and 6798 `family_not_built` first (wt-v22 `classification.py:159-165`). SAFT is confirmed at 26.5% insurance reserves. Remaining: CIK mismatch (15) |
| 6 | Definition file, its hash, recomputed; packet and code checks | **Partly** | Names only (6). e3_freeze ignores the names (7). Code and packet checked only at the freeze (5) |
| 7 | Freeze guards | **Holds** | Finished flag, lock, task and every slot are checked. The STOP flag is not (7) |
| 8 | The packet's own CIK; `panel_field_missing` | **Holds** | Remaining: zero market cap on the financial route (14); family kept on the census CIK (15) |
| 9 | Carried with a condition | Carried | The condition must also cover registering E3 (13) |
| 10 | `formation_waiting` | **Holds** | It never stalls the formation: it is called only for a retrospective map (`o2_run.py:116`) and from e3_run. Remaining: the flag is never cleared after an interrupted re-queue (1); the name filter (11) |
| 11 | B5 and sealed names dropped by code; counts only | **Holds in code** | No sealed name is printed or valued. Their identity can be derived (9) |
| 12 | Decision checked before anything is touched | **Partly** | o2_decide's verifier-record precondition is not checked first (2) |
| 13 | Frozen bytes; parse the hashed bytes | **Holds** | `e3_panel.py:146-153` |
| 14 | e3_panel takes the lock; e3_run needs every drawn packet | **Holds** | `e3_panel.py:158`, `e3_run.py:73-75` |
| 15 | Census reason; consumed names; SPEC §5; seeds | **Holds** | Seeds 1000 and 3000. Remaining: the pilot six and the 3N DEV set (17) |
| 16 | Packet hashes checked before the pass | **Holds** | `e3_run.py:76-77` |

## Fix list

| # | Item | Status | Owner |
|---|---|---|---|
| 1 | Re-queue resumes; o2_packets guards the lock; launch detached; check the state afterwards | **blocking before the Sunday re-queue** | coordinator (Claude) |
| 2 | `check_file` before touching anything | carriable; fix with 1 | coordinator |
| 3 | Stop on environment no_calls; anchor and closure hashes before each valuation; date guard | **blocking before the E3 smoke** | coordinator |
| 4 | Stop on `invalid` from an exception | **blocking before the E3 smoke** | coordinator |
| 5 | Fill-time checks (code state, packet, ticker, seed, T); HEAD and a clean tree before a pass | **blocking before the E3 run (step 3)** | coordinator |
| 6 | Top-level fields compared with the definition, in e3_run and e3_freeze | **blocking before the E3 run** | coordinator |
| 7 | e3_freeze compares the names and the top-level fields, and refuses on a STOP flag | **blocking before the freeze (step 4)** | coordinator |
| 8 | Orphan directory guard | carriable; fix with 5 | coordinator |
| 9 | Ruling on the seal complement | before RR_Q7 or any publication of the panel | operator (seal holder) |
| 10-17 | Minor and reporting items | carriable | coordinator |

**Verdict: APPROVED WITH CONDITIONS.** The conditions are items 1 and 3-7, each before the step named above, and item 9 before
publication. With them, the Q7 rejection is cleared.
