# Brief R26-E: close the revision-26 input gaps found by R26-D's offline probe

**Read first:**
- `SPEC_rev26_staged_analyst.md`, section 2 (the bridge) and section 5 (the consensus correction);
- the "Revision 26 build log" in `PLAN_terminal_reinvestment.md`;
- `tools/r26_forecast.py` (`bridge_to_x`, `invert_bridge`, `_bridge_inputs`);
- `tools/audit_202608/r26_stages.py` (`bridge_facts_from_row`, `load_bridge_facts`) and `r26_late.py` (`resolve_family`);
- `tools/audit_202608/r26_blind.py` (`op_margin_bar`, `consensus_corrected`);
- `scratch/rev23/pilot_r25/stage_r26.py` `check`, which runs the probe.

**Where:** rs2 `review-2026-10/r26-int`, worktree `scratch/rev23/wt-r26-int`, new commits on top of `372a6dc`.
- Commit by pathspec. Do not push.
- Never use the GPU, Ollama or a model.
- Every other arm stays byte-identical.

**The probe found** (packs built offline on tree `372a6dc`):
- `net_interest` is None for MSGE, TASK, DAC, BUD and MCY; MSGE has no `amortization_0`. Every stage-2 sample would be `bridge_unavailable_*`.
- PACS has no `owner_earnings_default_b` (an `R26InputError`).
- GOLD's family is operating, but its margin bar is on the X basis (`family_unresolved`).
- `consensus_corrected` is comparable only for TASK and GOLD.

## 1. Build: the base-year-calibrated bridge (a coordinator ruling; replaces the separate interest and amortization inputs)
- **Define, from filed base-year figures only:** `K_0 = OI_0 − X_0 / (1 − τ)`, in dollars. OI_0 is the filed operating income and X_0 the X-basis
  earnings that the pack already holds (x_L × rev_L). K_0 carries net interest, other non-operating items and the acquired amortization
  together, so that at the base year `X_0 = (OI_0 − K_0)(1 − τ)` exactly.
- **The bridge per year:** `X_margin_t = (op_margin_t − K_0 / R_t) × (1 − τ)`, with K_0 held in dollars and stamped
  `bridge_calibrated_to_base_year`.
  - When the filed amortization schedule exists, a refinement is allowed: K_t = K_0 − (1 − τ)/(1 − τ)·(A_t − A_0)… Keep it out: hold K_0,
    and list the held amortization as an assumption.
  - `invert_bridge` becomes the exact inverse.
- **Still required:** τ (measured), OI_0 and X_0. If any is missing: `bridge_unavailable_<what>`.
- **Financial family:** the identity, as before.
- **Tests:**
  - the identity at the base year, to 1e-12;
  - the round trip;
  - MSGE, TASK, DAC, BUD and MCY now have bridge inputs (or name exactly which one is missing).
- Remove the now-unused separate interest and amortization inputs, but only those your change orphaned.

## 2. Investigate and report each cause; fix only where the rule or code is wrong, and name the fix
- **(a) PACS `owner_earnings_default_b` is None:** why (which field), and does the revision-24 arm have the same gap? If revision 24 values
  PACS from another base, say which.
- **(b) GOLD:**
  - which family `population_ranges.family_for` gives it, and why the bar is on the X basis;
  - is the bar's basis rule, or the family rule, inconsistent with `resolve_family`?
  - Fix the inconsistency in one place, so that both read the same family.
- **(c) Consensus comparability:** for each of the 12 panel names (MSGE, TASK, PACS, DAC, BUD, GOLD, MCY, OGE, HNRG, PTCT, LPG, ITGR, the last
  five where their data exists offline), the exact `consensus_not_comparable` reason with its values (ratio, vintage test, share-count
  test, analyst counts).
  - Say whether each reason reflects a real basis problem or an over-strict test, with the evidence.
  - **Change no rule:** the coordinator rules on this.

**Then:** run `stage_r26.py check` (it is offline) on the 7 restoration names and report the per-name readiness.

**Tests:** the full rs2 suite must show the same 42 failures by name as `6bc2ad0`.

**Report (≤35 lines):**
- commits;
- the bridge change;
- the per-name readiness table (bridge inputs, base_cf, family, consensus status);
- causes (a), (b) and (c), with evidence;
- ambiguities.
