# CROSS_CHECK_Q7: blind review of the WO_Q7 E3 scripts, o2_requeue and the O3 runner copies (2026-10-31 03:32Z)

**Reviewer:** a fresh Opus, blind (no prior context beyond the brief). **Verdict: REJECTED.** There are 4 blocking findings. Findings 5, 6, 8
and 11 must also be fixed before the final panel is drawn, because the panel cannot be redrawn afterwards.

**Scope:** `scratch/rev23/m3q_e3/` (e3_panel, e3_run, e3_freeze, run_e3.cmd, launch_e3.vbs, register_e3_task.ps1), `m3o_run/o2_requeue.py`,
`m3o_run/o2_run.py` (I read the whole file; scratch is git-ignored, so the claim that `--wt` was the only change cannot be checked by
diff), and run_o3.cmd / launch_o3.vbs / register_o3_task.ps1. Specs: WO_Q7, WO_O2, SPEC_m3q §0, §2, §5-6, SPEC_m3o §3, RR_Q1 §5, LOG 10-31.

**What I ran (all read-only):**
- import checks and JSON reads;
- a read-only DuckDB query of MRI's store;
- `coe.cost_of_equity` called directly;
- `e3_panel.py 2026-11-30 --dry` (no map exists for that date): FileNotFoundError, exit 1, nothing written;
- simulations on copies of e3_run.py and o2_run.py, with fake panels, maps and locks, all inside my scratchpad
  (`<session scratchpad>/simtest.py`).

Nothing touched the GPU, Ollama, the live lock (it still holds 10544), m3o/inputs or any packet builder.

---

## Blocking

### 1. Blocking. E3 reads the live MRI anchors, so every valuation after the next asof roll becomes a permanent `no_call: coe_anchor_after_T`.

**Where:**
- `run.py:56` calls `coe.cost_of_equity`.
- `coe.py:36-49`: rf and g come from the current files. A leg dated after `T.date()` is refused unless `--allow-anchor-after-T` is passed.
- `rs2_data.py:957-971, 1055-1068`: the files read are MRI `outputs/*_anchor.json`.
- `e3_run.py:73-75` passes no pinned anchor directory, and `e3_run.py:89-94` fills the slot with whatever status comes back.

**Measured:**
- MRI's `raw_observations` has `max(date) = 2036-10-01`, from the GDPPOT projections. `anchors/service.py:114-115, 255-278` takes
  `asof = min(newest observation, today UTC)`, so each build's asof is the UTC date of the build.
- `MRI-Local-Daily` runs every day at 06:30 KST (21:30Z).
- The current files are asof 2026-10-30, built 2026-10-30T21:34:49Z.
- The refusal path is live: `coe.cost_of_equity('Industrials', T=2026-10-29T23:00Z)` gives
  `REFUSED coe_anchor_after_T: ['rf', 'g_anchor'] dated after 2026-10-29`. At the T1 time 2026-10-31T01:03:43Z the same call passes
  (r = 0.0878).

**Failure scenarios:**
- LOG 10-31 expects the final decision to move to a Sunday run (T2 ≈ 2026-11-01, 10:00-13:00Z) and schedules E3 for 11-03.
  The 2026-11-02T21:30Z build is asof 11-02, which is later than T2's date. So on 11-03, every slot that reaches the cost of equity is
  refused, and the other callable slots stop earlier on data refusals. Of the 56 callable names × 2 seeds, none is valued.
- Each refused slot is recorded as filled, and "a run is never repeated", so the panel is spent with no valuation at all.
- If T1 stands, the roll comes one day earlier (2026-11-01T21:30Z).
- Even in the best case, coe's day-granularity check accepts an anchor built up to about 21 h after T (dated T's day). That is a quiet
  point-in-time leak.

**Fix:**
- Snapshot `cost_of_capital_anchor.json`, `long_run_growth_anchor.json` and `sector_multiple_bands.json` from the build whose
  `built_at ≤ T` into `m3q_e3/anchors_<T>/`. Record each file's sha256 and `built_at` in the panel.
- Run run.py with `MRI_ANCHORS_DIR=<snapshot>`. `paths.py:101` honours it.
- e3_run refuses to start if a snapshot hash differs or `built_at > T`.
- Record the sha256 of `rs2-local/cache/reference_closure.json` (asof 2026-10-04, valid to 11-18), and have e3_freeze check that it has
  not changed.
- Never "fix" this with `--allow-anchor-after-T`: that stamps the refusal away and lets post-T anchors in.
- **Time-critical:**
  - T1's anchor set (on disk now) is overwritten at 2026-10-31T21:30Z.
  - T2's set (that build) exists only until 2026-11-01T21:30Z. Copy each set while it exists. Otherwise it can only be rebuilt with
    `build_anchors(as_of=..., write=False)`.

### 2. Blocking. `gpu_ok()` can never pass, so the runner never values anything.

**Where:** `e3_run.py:40`, which runs `from qwen_c import runner, llm_provider`.

**Measured:** in wt-m3q, `python -c "from qwen_c import runner, llm_provider"` raises
`ImportError: cannot import name 'llm_provider' from 'qwen_c'`. `qwen_c/__init__.py` is empty, and `runner.py:74` imports
`llm_provider` as a top-level module. `runner.llm_provider.OLLAMA_URL` resolves to `http://127.0.0.1:11434/api/chat`.

**Scenario:** every pass prints "GPU busy or unreadable: stopping" and exits 3, and the task retries every 15 min forever. The log reads
like a busy GPU. This fails safe, and the step-2 smoke would show it, but steps 2 and 3 cannot run.

**Fix:**
- Use `from qwen_c import runner; runner.gpu_preflight(runner.llm_provider.OLLAMA_URL)`.
- Return a distinct exit code and message when the probe itself crashes (a traceback without `RunRefused`), so a code error is never
  reported as `gpu_busy`.

### 3. Blocking. Transient and systemic failures fill slots permanently, and the runner never stops on a defect.

**Where:**
- `e3_run.py:81-88`: after a crash the runner moves on to the next slot. A second crash of a slot fills it as `runner_failed`.
- `e3_run.py:89-94`: any exit-0 result fills the slot, whatever its status: `timeout`, `infra_retry`, `infra_fatal` or `engine_defect`.
- `run.py:76-88, 120-147` has no infrastructure retry: the status is the transport outcome.
- `sec_store.py:32, 127-152`: for every valuation, companyfacts and submissions are refetched online. Any transport failure raises
  `FetchFailed`, so the run exits 1.
- `runner.py:376-385`: `gpu_preflight` sees only Ollama's `/api/ps`. A game holding VRAM is invisible to it.

**Measured** (simulation on copies, with a fake 3-name panel):
- (A) run.py exits 1 with `getaddrinfo failed`. Pass 1 sets `failures=1` on 6/6 slots. Pass 2 makes all 6 `runner_failed` and writes
  `finished_2026-10-30.flag`.
- (B) result.json says `timeout` or `infra_retry` with exit 0. Both slots are filled on the first pass and the finished flag is written.

**Scenarios:**
- A 15-30 min network or SEC outage spends every remaining slot.
- Ollama returning HTTP 500 because a game holds the VRAM fills every slot it reaches with `infra_retry`.
- An `engine_defect` on one route fills every name on that route in a single pass. That breaks the standing rule that a runner stops
  at the first code-defect failure.
- None of these slots can be rerun under "a run is never repeated".

**Fix:**
- Stop the pass, with a distinct exit code, on any crash, on `engine_defect`, and on `timeout`, `infra_retry` or `infra_fatal`.
  Do not fill those slots.
- Before any retry, rename the run directory aside to `<dir>_attempt<k>`, so nothing is overwritten (run.py's run directory is
  deterministic, which is why the smoke directories had to be renamed by hand).
- Mark `runner_failed` only when the same slot fails twice while other slots succeed. Otherwise write a STOP flag for a human.
- Optional: run the second seed with `--offline`, so both seeds read the same companyfacts bytes.

### 4. Blocking. o2_requeue releases the lock before o2_decide and o2_packets run. The formation task then marks itself finished, or loses updates, and the T2 batch does not run.

**Where:**
- `o2_requeue.py:26-39` holds the lock only while it moves the map aside. `:40-43` then runs o2_decide and o2_packets without it.
- `o2_run.py:122-123` writes the finished flag when no name is `to_run` or `pending`. A `to_build` name does not count as unfinished.
- `o2_run.py:89, 120` and `o2_packets.py:29, 47` each rewrite the whole map from their own in-memory copy.

**Measured:**
- Simulation C ran a copy of o2_run.py on a map whose names were all `to_build`: rc 0, the finished flag was written, and no run was
  attempted.
- Building the 58 T1 packets took 4 min 48 s (wt-m3o packet mtimes, 10:14:58 to 10:19:46 KST). A 15-min trigger therefore lands inside
  the requeue window about one time in three.
- LOG 10-31 rules that the requeue will be used after the Sunday runs.

**Scenarios:**
- (A) The trigger fires after o2_decide has written the T2 map (every name `to_build`). The flag is written at once, `launch_o2.vbs:8`
  quits on every later trigger, and the T2 names reach the 11-02 open as `analysis_pending`. o2_requeue's own summary still prints
  `to_run 58`, so nothing looks wrong.
- (B) The trigger fires while packets are being built. Sixteen minutes later, o2_run's first save resets every name built after its
  snapshot to `to_build` with a null packet. It then writes the flag.

**Fix:**
- Release the lock only after line 43, in a `finally`.
- Count `to_build` as unfinished in o2_run's flag test.
- Have o2_packets refuse to run while a live runner holds the lock.

---

## Must be fixed before the final panel is drawn (the panel is fixed once)

### 5. Material. Names missing from census_1a_routing.json never get the B7 balance-sheet confirmation.

**Where:** `e3_panel.py:72-82` (`route()`). Rows from `census_measure` (`:53-68`) have no `desk_route`.

**Measured:**
- The routing table holds only the 160 census rows.
- The T1 dry panel has 7 `census_measure` names (ADT, HAE, ITGR, SAFT, UNIT, VSTS, XHR). SAFT goes to the financial route with no test.
- CROSS_CHECK_Q3 item 7 ("SPEC §5's balance-sheet test") was carried to E3 for exactly this case.
- `route()` would also send a `family_not_built` mortgage REIT whose `desk_route` is financial (CIM) to the financial route. That
  contradicts `run.py:31` and WO_Q7 ("REIT names stay family_not_built").

**Scenario:** a name new to the book takes the wrong route without any warning:
- a non-lender with a financial SIC (the V/PRCH case) is valued on retained equity;
- a lender with an operating SIC (the SEZL/STT case) goes to the operating route.

Either way the valuation is wrong.

**Fix:**
- Compute `desk_route` for `census_measure` names with `census_1a_addendum.route`, on the same store and asof, and stamp
  `routing_source`.
- A financial name that cannot be tested becomes the named no_call `financial_unconfirmed`.
- Override to financial only when the census family is financial or operating.

### 6. Material. Nothing hashes the panel definition before valuation, so the acceptance test "the panel file predates the first result" cannot be run.

**Where:** `e3_panel.py:121, 133` and `e3_run.py:86, 93` rewrite `panel_<T>.json` after every packet and every run.
`e3_freeze.py:34` hashes only the final file.

**Scenario:**
- An edit between runs to a family, CIK, sector or membership is invisible to the witness. So is a slot cleared after a post-smoke code
  fix.
- The file's mtime, and its creation time after `os.replace`, move with every save. The acceptance test has nothing to read.

**Fix:**
- At creation, write `panel_<T>.def.json`, never rewritten: the names and every per-name field except `runs`. Log its sha256, and
  preferably push it the way the witness is pushed, before the smoke.
- e3_run refuses to run if that hash does not recompute.
- e3_freeze recomputes it and adds it to the witness line. It also checks two things:
  - every result has the same `versions.git`, namely `[8d25d85…, clean]`;
  - every `result.packet_sha256` equals the panel's packet hash.

### 8. Material. run.py receives the census CIK and never checks it against the packet's own CIK.

**Where:** `e3_run.py:73` (the CIK from `e3_panel.py:114`). Nothing in qwen_c/value compares `--cik` with `packet["cik"]`
(grep: the only CIK use is `run.py:167`).

**Measured:**
- For the book, all 58 packets have a sha256 that recomputes and a CIK equal to the census CIK.
- The 10 drawn packets are not built yet. Their CIK will come from the screener's `cik_map`, not from the census `id_map`.

**Scenario:** for a share class or a reassigned ticker, the two CIKs differ. The name is then valued on another entity's facts, against
this entity's evidence, and the result looks normal.

**Passing "None" (checked):** a "None" string never produces a wrong valuation without a warning. Each case is either refused or fails:
- sector "None": refused as `coe_unavailable` (`coe_loading('None')` returns `(None, None, 'unmapped_sector(None)')`);
- market cap "None": argparse exits 2 (`run.py:161` parses it before the family check), so the slot becomes `runner_failed` after two
  tries, even for financial and family_not_built names that never use the market cap;
- cik "None": `int('None')` raises ValueError (`facts.py:114`), so `runner_failed`;
- family "None": refused as `family_not_routed`;
- a NaN or zero market cap: refused as `market_cap_unavailable` (`inputs.py:198`).

**Fix:**
- Pass `pk["cik"]`, or refuse when it differs.
- For a missing field, record a named no_call in e3_run instead of two crashes.

### 11. Material. A B5 holdout, CLDT, is in the draw, and nobody has checked the panel against the Stage-2 sealed names.

**Where:** `e3_panel.py:30, 103-106` excludes only the operator-excluded names.

**Measured:**
- The T1 hash order is [panel draw list kept local: sealed-name rule]
- SPEC_m3q §0 item 8 and B5: CTVA, NHC, TTAM, CLDT and the Stage-2 sealed names "are not opened by 3Q".
- PREREG_m3n excluded the four by ticker.
- e3_panel builds CLDT's packet online and records a result for it.

**Fix:**
- Before the final draw, add the B5 tickers [panel draw list kept local: sealed-name rule]
  (11th) takes CLDT's place.
- The operator, as seal holder, runs a check of the Stage-2 names against the panel that reports only the size of the overlap, or rules
  that a prospective T does not open them.

---

## Material, can be carried with a condition

### 7. Material. e3_freeze will write a witness while slots are unfilled or a runner is still live.

**Where:** `e3_freeze.py:33-37` counts `unfilled` and never stops on it. There is no check of the lock, the finished flag or the
scheduled task.

**Scenario:** the freeze is pushed with unfilled > 0 while RS2-M3Q-E3-Runner is still registered. The next pass then fills those slots
after the witness, and the witness hash stops matching the panel.

**Fix:** refuse unless all of these hold: `unfilled == 0`, `e3/finished_<T>.flag` exists, the lock is free, and the task is absent.
**Condition:** fix before step 4.

### 9. Material. The lock is not taken atomically, and a reused pid stalls it.

**Where:** `o2_run.py:56-65` checks that the file exists, reads it, calls `pid_alive`, then writes. A half-written file raises
ValueError and is treated as free.

**Measured:**
- D2: two copies started against a stale lock, with the `pid_alive` window widened to 0.3 s. Both got `take_lock=True`.
- E: a live pid of an unrelated process in the lock made `take_lock` return False indefinitely.

**Scenarios:**
- At logon or wake, all three tasks start within milliseconds (AtLogOn + StartWhenAvailable, `register_*_task.ps1:10-13`), so two
  runners can share the GPU. `gpu_preflight` passes for both, because they use the same model. Their requests then either queue behind
  each other or compete for VRAM. Either way the recorded timings are wrong, and any timeout or 5xx fills slots as in finding 3.
- A reboot kills the holder without its `finally`. The dead pid is then reused by a long-lived process, and every runner logs "another
  runner holds the lock" every 15 min, indefinitely.

**Fix:**
- Take the lock with `os.open(O_CREAT|O_EXCL)`, or `msvcrt.locking` on a handle kept open, which the OS releases when the process dies.
- Store the pid with the process creation time (GetProcessTimes) and compare both.

**Condition:** until this is fixed, check `runner*.out` after any reboot or wake.

### 10. Material. Nothing lets a formation pre-empt a lower-priority batch: each runner keeps the shared lock for its whole batch.

**Where:** `e3_run.py:53-99` and `o2_run.py:83-124` hold the lock for the entire loop. RS2-M3O-Retro-Runner is already armed: it is
Ready, fires every 15 min from 12:01:51 KST, and `runner_o3.out` shows it deferring. It was armed before this cross-check.

**Measured:**
- T1: 7 complete, 51 to run, mean 945 s per name, so it ends around 10-31 16:35Z.
- O3: 58 to run, about 15 h, ending around 11-01 08:00Z. The Sunday scoring runs land at 10:00-12:35Z (LOG 10-31).
- Within each 15-min cycle, O3's trigger fires 2 min 13 s before the formation's. So if the T1 process ends with a pending name, O3
  takes the lock about 85% of the time.

**Scenario:** O3 (or a later E3) is in mid-batch when the requeue, or a pending second attempt, needs the GPU. o2_requeue stops at
line 27, or the formation names wait 15-20 h and reach the open as `analysis_pending`. SPEC_m3q §6 ("Formation runs pre-empt 3Q GPU
work") is not implemented.

**Fix:** before each run, e3_run and the `--wt` (retrospective) mode of o2_run check whether any live formation map has
`to_build`/`to_run`/`pending` names and no finished flag (or whether a PREEMPT file exists). If so, they exit and release the lock.
**Condition:** until then, disable RS2-M3O-Retro-Runner if it is still running when the Sunday re-decide is due, and register E3 only
after the T2 batch has finished.

---

## Minor (carriable)

**12.** `o2_requeue.py:29-36` moves the map aside (and the flag) before it knows that o2_decide will succeed (`:40-43`).
- If o2_decide stops (no verifier record, or a stop for a reason other than a changed decision), there is no `formation_<T>.json` and
  the task crashes every 15 min. Nothing is lost, but recovery is by hand.
- Fix: first confirm that `FL.decision_for` gives a run id different from the map's.

**13.** `e3_panel.py:92` hashes the bytes, then `:95` reads the file a second time to parse it.
- Fix: parse the hashed bytes.
- The WO_O2 freeze should also keep the frozen bytes as `formation_<T>.frozen.json`, for e3_panel to read. Under SPEC_m3o A1S, names
  still pending at the freeze are run afterwards and change the live map, after which no file matches the frozen hash.

**14.** e3_panel takes no lock. `e3_run.py:95` leaves names without a packet out of the finished test.
- If e3_run starts before all 10 drawn packets exist, the two scripts' whole-file rewrites overwrite each other, and the flag is
  written without the drawn names.
- Fix: e3_panel takes the lock, and e3_run refuses unless every drawn name has `packet` or `packet_refused`.

**15. Reporting:**
- `e3_panel.py:50, 64` drops the census `reason`, so WO step 6's "no-call counts by reason" will read `family_not_routed` for all 12
  no-calls. Carry the census reason (REIT / pre_profit / regulated_utility) into the panel.
- Mark every consumed name, not only MCY and ITGR:
  - TASK, PACS, VSNT and PTCT (the rev-26 panel);
  - MA, CMRE, HRTG and ECPG (3M contract tuning);
  - MRP, LIND and STT (rev-25 Stage 1).

  Report B6 with and without them.
- SPEC_m3q §5 still gives D2 with δ for equity REITs, but ruling 17 (RR_Q3) refuses them, and 10 of the 12 T1 no-calls are REITs.
  Amend §5 and §9.
- SPEC_m3q §2 gives seeds 1000 and 3000, while `e3_run.py:27` uses 1000 and 2000. Record the deviation.

**16.**
- An uncaught exception at `e3_run.py:76` (rereading the packet) repeats at the same slot on every pass and blocks every later name.
- e3_run never checks `sha256(packet)` against the panel's `packet_sha256`.
- Fix: catch and record the exception, and verify the hash.

---

## Verified correct

- **Run directories:** `e3_run.py:78-79` equals `run.py:96` (`runner.t_compact`, `runner.py:125-126`, on the `load_packet` file bytes,
  `runner.py:347-351`). The formula reproduces the real directories `DAR_20261030T020000Z_1da0b96591b1_1000` and
  `CTBI_…_789439fac5e1_1000` (2 of 2). There is no earlier valuation at the formation T (6 run directories, all smokes).
- **Releasing the lock:** `release_lock` removes the lock only when the file holds the caller's own pid (`o2_run.py:131`).
  - e3_run releases only after a successful `take_lock` (`:53-56`, `:98-99`).
  - On o2_run's early return the release does nothing.
  - No runner can remove a lock it does not hold, except after the race in finding 9.
- **Draw:**
  - Recomputed from the live map's output commit: 101 watchlist names after exclusions, the first 10 identical to the dry panel, no
    overlap with the book, no filter on family.
  - `run_id` is a string, so the hash input is stable.
- **Book packets:** all 58 sha256 recompute and all CIKs match. Both worktrees have builder v7. wt-m3q is clean at 8d25d85.
- **O3 copies:**
  - The `--wt` default is unchanged, the flags are kept per T, and the outputs go to separate files.
  - All 58 packets of the 09-30 map are under wt-m3o-retro, which is clean at d2f3f15.
- **Point in time:**
  - Sector and market cap come from the output commit, read through git. Families come from the census as of 10-18.
  - Facts are filtered by acceptance ≤ T.
  - The only way after-T data reaches E3 is the anchors (finding 1).
  - The only ways a result can follow the witness or the outcome are human reruns or edits, which findings 3, 6 and 7 close.

## Fix list

| # | Item | Blocking / carriable | Owner |
|---|---|---|---|
| 1 | Pinned anchor snapshot (`built_at ≤ T`) through `MRI_ANCHORS_DIR`; copy the T1 set before 10-31T21:30Z and the T2 set before 11-01T21:30Z | **blocking** | coordinator (Claude) |
| 2 | Import in `gpu_ok` | **blocking** | coordinator |
| 3 | Stop on crash, defect or transport outcome; move aside before any retry | **blocking** | coordinator |
| 4 | o2_requeue holds the lock through o2_packets; `to_build` counts as unfinished | **blocking, before the Sunday requeue** | coordinator |
| 5 | B7 test for names missing from routing; CIM case | blocking before the panel is drawn | coordinator |
| 6 | Definition hash, plus code-version and packet checks in e3_freeze | blocking before the panel is drawn | coordinator |
| 8 | Packet CIK; named no_calls for missing fields | blocking before the panel is drawn | coordinator |
| 11 | Exclude the B5 tickers from the draw; check against the Stage-2 seal | blocking before the panel is drawn | coordinator; operator (seal) |
| 7 | e3_freeze guards | carriable until step 4 | coordinator |
| 9 | Atomic lock with creation time | carriable (watch the logs after a reboot) | coordinator |
| 10 | Pre-emption, or disable O3 around the requeue | carriable with the stated condition | coordinator |
| 12-16 | Minor items | carriable | coordinator |
