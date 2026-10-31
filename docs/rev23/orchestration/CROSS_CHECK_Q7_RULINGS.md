# CROSS_CHECK_Q7 rulings (Claude, 2026-10-31, operator asleep: proceed-without-approval rule)

The review REJECTED the WO_Q7 scripts and o2_requeue: 4 blocking findings, 4 to fix before the panel is drawn. Every finding is
accepted. Fixes are in the scratch scripts (git-ignored; the files themselves are the record) and in WO_Q7 (revised). A fresh blind
re-check follows this batch before any of it touches the GPU.

| # | Ruling | Fix |
|---|---|---|
| 1 | Accepted, blocking and time-critical. My error: I did not trace where the cost of equity's anchors come from | `m3q_e3/snap_anchors.py` plus task `RS2-M3Q-AnchorSnap` (every 30 min) copy each MRI build with a sha256 manifest; the T1 set (built 10-30 21:34Z) was copied at 03:35Z. `e3_panel` pins the newest copy built at or before T and the closure file's sha256; `e3_run` sets `MRI_ANCHORS_DIR` and refuses if any of them fails to recompute. `--allow-anchor-after-T` is never used |
| 2 | Accepted | `runner.llm_provider.OLLAMA_URL`; a probe that crashes stops with its traceback, not "GPU busy" |
| 3 | Accepted | Only model or code outcomes fill a slot (ok, valuation_incomplete, invalid, malformed, context_overflow, no_call). A crash, engine_defect, timeout or infra outcome moves the run directory aside as `_attempt<k>` and stops the pass (exit 6); the third failure of a slot writes `e3/STOP_<T>.flag`, and the launcher idles |
| 4 | Accepted, blocking before the Sunday re-queue | `o2_requeue` confirms the decision changed before touching anything, writes `o2/preempt.flag`, waits for the lock, holds it through o2_decide and o2_packets, and releases it only after; a stop leaves preempt in place. `o2_run` counts `to_build` as unfinished |
| 5 | Accepted | census_measure names get `census_1a_addendum.route` on the same store and asof (SAFT is confirmed: insurance reserves at least 10% of assets); an untestable financial name is `financial_unconfirmed`; a `family_not_built` name never becomes financial |
| 6 | Accepted | `panel_<T>.def.json`, written once after the last drawn packet; its hash is logged and recomputed by e3_run and e3_freeze; e3_freeze checks every result's packet sha256 and its clean code commit `[8d25d85…, False]` |
| 7 | Accepted, fixed now | e3_freeze refuses unless every slot is filled, the finished flag exists, the lock is free and the task is removed |
| 8 | Accepted | The panel takes the packet's own CIK and records a different census CIK; a missing sector, market cap, CIK or family is the named no_call `panel_field_missing` |
| 9 | Accepted, carried with the condition | The running T1 formation process uses the current pid-file lock, so changing the lock's scheme now would let a new runner ignore it. After the final formation batch: an `O_EXCL`/`msvcrt` lock with the process creation time. Until then I read `runner*.out` after any reboot or wake |
| 10 | Accepted | `o2_run.formation_waiting()`: a retrospective (`--wt`) pass and every E3 valuation yield (exit 5) while a contemporaneous map has work left or `o2/preempt.flag` exists. E3 is registered only after the final formation batch |
| 11 | Accepted. The B5 rule is in SPEC_m3q §0 and I missed it | CTVA, NHC, TTAM, CLDT and the Stage-2 sealed names are dropped from book and draw by code; only counts are recorded (2 sealed names in the T1 book, 1 in the watchlist), and I have not looked at which. **Operator:** the seal holder may rule that a prospective T does not open them, in which case they can be valued at the next formation |
| 12 | Accepted | Covered by 4: the decision is checked first |
| 13 | Accepted | At the WO_O2 freeze the map's bytes are kept as `formation_<T>.frozen.json`; e3_panel draws only from that file |
| 14 | Accepted | e3_panel takes the lock; e3_run refuses unless every drawn name has a packet or a recorded refusal |
| 15 | Accepted | The census reason is kept; WO_Q7 lists the consumed names, reported with and without; SPEC_m3q §5's REIT row is corrected (not built: a named no-call); seeds are 1000 and 3000, as SPEC_m3q §2 |
| 16 | Accepted | e3_run checks every packet's sha256 before the pass, so a bad packet stops the pass instead of repeating at one slot |

**Also found while fixing (mine):** the O3 runner `RS2-M3O-Retro-Runner` was registered before this review. With finding 10's yield in
place it keeps the formation first. The T1 batch is unaffected: its process loaded `o2_run.py` before these edits.

**Operator ruling on item 11 (2026-10-31):** "keep them out". The B5 holdouts and the Stage-2 sealed names stay out of E3 and of later 3Q panels; only counts are recorded.

## CROSS_CHECK_Q7b (re-check of the fixes): APPROVED with conditions. Rulings (Claude, 2026-10-31)

| # | Ruling | Fix |
|---|---|---|
| 1 | Accepted, blocking before the Sunday re-queue | o2_requeue calls o2_decide and o2_packets in-process (the lock's pid is the worker), resumes from every interrupted state (map with to_build names; missing map beside one superseded map; a complete map still on the old run is moved aside again), and clears preempt.flag only when no name is to_build. It is launched detached |
| 2 | Accepted | o2_decide.check_file is checked before anything is touched |
| 3 | Accepted | coe_unavailable and coe_anchor_after_T no_calls never fill: STOP at once. The anchor copy, closure and packet are recomputed before every valuation; no pass starts within an hour of the closure's 45-day limit (2026-11-18 15:00Z) |
| 4 | Accepted | An `invalid` whose failure is one of the six exceptions checks.py catches is a STOP, not a fill |
| 5 | Accepted | Before a pass: wt-m3q HEAD equals the definition's commit with a clean tree. At fill: versions.git equals [commit, False], and packet sha256, ticker, seed and T equal the slot's; otherwise STOP |
| 6 | Accepted | e3_run reads anchors, closure, code and names from the definition, and stops unless every top-level field and every name of the panel equals it |
| 7 | Accepted | e3_freeze makes the same comparisons and refuses while a STOP flag exists |
| 8 | Accepted | A directory found before a valuation is moved aside as `_orphan<k>` and recorded; every move-aside picks the first free suffix |
| 9 | Ruled by the operator ("keep them out", 10-31): the sealed names stay unvalued. Their identity can be derived by set difference between the frozen map and the panel, so WO_Q7 and RR_Q7 say "unvalued", not "the seal stays closed", and the panel's name list is never published beside the map | wording in WO_Q7 |
| 10 | Accepted, carried (minor) | The bill-rate series is stable over a past window, and a failed read fails the slot. RR_Q7 compares each result's coe rf, g_anchor and closure_erp with the pinned files by value |
| 11 | Accepted | formation_waiting matches only `formation_YYYY-MM-DD.json` and prints what caused a yield; o2_requeue waits up to 4 h |
| 12 | Accepted | e3_run and e3_freeze strip non-hex characters from the hash |
| 13 | Accepted as a condition | E3 is registered only after finished_2026-09-30.flag exists (or after the Q7-9 lock) |
| 14 | Accepted | The market cap is required only on the operating and commodity routes; a financial name passes 0, which its route never reads |
| 15 | Accepted | A CIK mismatch is the named no_call cik_mismatch; the panel records the census code commit (wt-v22) |
| 16 | Accepted | anchor_set skips `.tmp` and `.stale` copies; snap moves a crashed `.tmp` aside as `.stale<k>` |
| 17 | Accepted, carried | RR_Q7 checks the consumed list against the rev 24 pilot six and the 3N DEV set too |

## CROSS_CHECK_Q7c (third blind check): APPROVED with conditions. Rulings (Claude, 2026-10-31)

| # | Ruling | Fix and evidence |
|---|---|---|
| 1 (double launch) | Accepted | o2_requeue re-reads the map under the lock and skips the move when it already holds the new run. Only the RS2-M3O-Requeue task launches it (IgnoreNew) |
| 2 (kill between renames) | Accepted | The finished flag is renamed before the map; after the packets, a finished flag beside to_run names is set aside as `_stale_<run>`. A missing map beside any number of superseded maps is resumed at the current decision (found by rerunning the reviewer's simulation: a second re-queue killed after its move stopped for a human) |
| 3 (post-checks) | Accepted | I check after each re-queue: preempt.flag gone, no to_build, the map's run equals the decision, the old flag set aside, RS2-M3O-Formation-Runner still registered (it stays until the final batch ends; WO_O2 step 7) |
| 4 (exception in an earlier attempt) | Accepted | judge() scans every attempt's checks failures |
| 6 (unmapped sector) | Accepted | `coe_unavailable` with exactly `missing ['loading']`, against a verified pinned copy, is the name's own no_call and fills |
| 7 (save blocked by a reader) | Accepted | o2_run.save retries os.replace on PermissionError for up to 10 s |
| others | Accepted, carried as minor | a pin changed mid-valuation; the closure guard fires early (safe side); e3_freeze prints the hash as typed; the DuckDB export race fails the slot, which the failure path handles |

**Evidence:** the reviewer's simulations (scratchpad q7c), rerun on the fixed copies (q7e, q7f, q7g). sim_rq: every scenario converges
with no duplicated and no unrun names; the stops are the intended safe stops (unverified run, builder mismatch, wait expiry).
sim_e3c: fills, non-fills, environment no-calls, checks exceptions (including in attempt 1), strikes and freeze behave as ruled.

**Scheduled:** RS2-M3O-Requeue (from 2026-11-01 14:45Z, every 30 min for 18 h: check_new_runs then o2_requeue) and
RS2-M3P-Bench-Runner. The requeue fires only after the weekend runs, so the T1 batch, WO_O3 and the benchmark use the GPU first.
