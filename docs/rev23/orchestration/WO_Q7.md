# WO_Q7: the 3Q E3 prospective panel of the 2026-10-30 formation (Claude executes, 2026-10-31 to 11-04)

**Goal:** value every name of the E3 panel (SPEC_m3q §6 E3) once per seed on checks v9, freeze the results and push their hash
to the records branch before any outcome is read; then the blind readers and the bias report; then CLOSE_3Q against the B6 bar.
Valuation stays diagnostic only (B9): nothing here touches selection, weights, exits, the overlay, `rn_depth` or KIS.

## Code and roots

- **Valuation code:** rs2-local `review-2026-10/m3q` at `8d25d85` (checks v9, prompt v7 / fin.v5), worktree `scratch/rev23/wt-m3q`.
  Its packet builder is the formation's (`m3m.packet.builder.v7`; the only non-valuation change since `d2f3f15` is
  `sec_store`'s companyfacts refetch, CROSS_CHECK_Q 8).
- **Scripts:** `scratch/rev23/m3q_e3/` (`e3_panel.py`, `e3_run.py`, `e3_freeze.py`, `run_e3.cmd`, `launch_e3.vbs`,
  `register_e3_task.ps1`).
- **Results:** `wt-m3q/cache/m3q/runs/<ticker>_<T>_<packet sha12>_<seed>/result.json`, recorded with their sha256 in
  `m3q_e3/panel_2026-10-30.json`.

## The panel (fixed before any valuation)

*Revised 2026-10-31 after CROSS_CHECK_Q7 (REJECTED; rulings in CROSS_CHECK_Q7_RULINGS.md).*

- **Held out, from book and draw alike, before any outcome:** SENEA, SENEB, MOV, MG (operator) and the B5 holdouts (SPEC_m3q §0
  item 8): CTVA, NHC, TTAM, CLDT and the Stage-2 sealed names. Code drops the sealed names and records only their count, so they stay
  unvalued (operator, 10-31: "keep them out"). Their identity can be derived by set difference between the frozen map and the panel
  (CROSS_CHECK_Q7b 9), so the panel's name list is never published beside the map. On the T1 map, 2 sealed names were in the book and 1 in the watchlist.
- **Book:** every other book name of the frozen WO_O2 map (`formation_<T>.frozen.json`). FQ is a subset of the book. Each uses the
  map's own packet.
- **Draw:** the first 10 remaining names of the decision run's `watchlist` band in `sha256("<run_id>:<ticker>")` order, whatever
  their family. Their packets are built in wt-m3q exactly as `o2_packets.py` builds the formation's.
- **Family (B7, SPEC_m3q §5):** the census family (`census_1a.json`, asof 2026-10-18, or `census_1a.measure` at that asof for a name
  the census lacks), confirmed by the balance-sheet test (`census_1a_routing.json`'s `desk_route`, or `census_1a_addendum.route` on
  the same store for a census_measure name):
  - a confirmed financial or operating name is financial (STT, SEZL, SAFT);
  - an unconfirmed financial name is operating (V, PRCH);
  - a financial name that cannot be tested is the named no_call `financial_unconfirmed`;
  - `family_not_built` (pre-profit, utility, REIT) stays a named no_call whatever its route; the census reason is kept.
- **CIK:** the packet's own; a different census CIK is recorded.
- **Sector and market cap:** `stocks.json` at the map's output commit, read through git. A missing field is the named no_call
  `panel_field_missing`.
- **Anchors (CROSS_CHECK_Q7 1):** MRI rebuilds the cost-of-capital and growth anchors every day at 21:30Z and stamps them with
  that date, so the live files soon postdate T and the runner would refuse every name (`coe_anchor_after_T`). Task
  `RS2-M3Q-AnchorSnap` copies each build into `m3q_e3/anchors_by_build/<built_at>/` with a sha256 manifest; the panel pins the
  newest copy built at or before T, and `e3_run.py` passes it as `MRI_ANCHORS_DIR`. The reference closure file's sha256 is
  recorded too. `--allow-anchor-after-T` is never used.
- **The definition:** `panel_<T>.def.json` is written once, after the last drawn packet: every field but the runs. Its sha256 is
  logged, written to `e3/def_sha256_<T>.txt`, and recomputed by `e3_run.py` before every pass and by `e3_freeze.py`.
- **Dry run on the T1 map (10-31 04:20Z):** 66 names (56 book, 10 drawn); 30 operating, 14 financial, 12 commodity, 10 no_call.
  Drawn:  [panel draw list kept local: sealed-name rule]
- **Consumed names (CROSS_CHECK_Q7 15),** reported with and without: MCY, ITGR, TASK, PACS, VSNT, PTCT (the rev 26 panel); MA,
  CMRE, HRTG, ECPG (3M contract tuning); MRP, LIND, STT (rev 25 Stage 1). A new T is a prospective valuation, so they stay.

## Steps

1. **After the WO_O2 map is frozen** (its sha256 logged, its bytes kept as `formation_<T>.frozen.json`):
   `python e3_panel.py 2026-10-30 --map-sha256 <hash>`. It takes the runner lock. Log the definition hash it prints and write it to
   `e3/def_sha256_2026-10-30.txt`.
2. **Smoke:** `python e3_run.py 2026-10-30 --def-sha256 <hash> --ticker <the first callable name>` (both seeds). Read both
   results: statuses, checks, no engine_defect, the anchor copy in `coe`. A code defect stops the batch.
3. **Run:** `register_e3_task.ps1`, only after the formation's final batch has finished and `o2/finished_2026-09-30.flag` exists
   (CROSS_CHECK_Q7b 13).
   - `e3_run.py` shares WO_O2's `runner.lock` and yields to any contemporaneous formation map with work left
     (`o2_run.formation_waiting`, exit 5).
   - It checks `gpu_preflight` before each valuation (exit 3 if busy).
   - Seeds 1000 and 3000 (SPEC_m3q §2; the repair turn adds 50000, as `run.py`).
   - A slot is filled only by ok, valuation_incomplete, invalid, malformed, context_overflow or no_call. A crash, engine_defect or
     transport outcome moves the run directory aside as `_attempt<k>` and stops the pass (exit 6). The third failure of one slot
     writes `e3/STOP_<T>.flag` and the launcher stays idle until a human looks.
   - About 56 callable names x 2 seeds x ~8-11 min = 15-20 h.
4. **Freeze and witness:** remove the task, then `python e3_freeze.py 2026-10-30 --def-sha256 <hash>`.
   - It refuses unless every slot is filled, the finished flag exists, the lock is free and the task is gone.
   - It recomputes the definition, every result, the anchor copy and the closure file, and checks each result's packet sha256 and
     clean code commit.
   - Commit its line as `docs/rev23/witness/e3_2026-10-30.txt` to rs2-local `docs/rev23-records` and push it before any outcome is
     read. Hashes only.
5. **Blind readers:** fresh Opus readers, inputs masked, the amended rubric (B6), on the frozen results.
6. **Report:** RR_Q7 with the B6 measures (V checks pass or are honestly incomplete on at least 80% of callable names; at least 80%
   coherent and 0 incoherent; direction unanimity across seeds at least 80%), with and without the consumed names; no-call counts
   by reason; the bias report (median log(value/price) per family beside the panel's; reported, never tuned). Then CLOSE_3Q.

## Acceptance

| Test | Pass |
|---|---|
| Panel fixed before valuation | the definition's map_sha256 equals the logged freeze hash, and its own sha256 was logged before the smoke |
| Every slot filled | each callable name has both seeds filled; no STOP flag left unresolved |
| Records recompute | `e3_freeze.py` recomputes every result sha256 |
| Witness precedes outcomes | the witness push time is before the first E4 mark |
| Nothing else changed | no screener, overlay, `rn_depth`, KIS or schedule change other than the temporary task, then removed |
