# Brief SF: the short form (desk schema 25.2) and its 3-name test mode (operator approved, 2026-10-18)

## Why
The 25.1 bridge gave D2 its revenue and margin path, but Qwen looped on the normalization checks (`PLAN_terminal_reinvestment.md`, the
sections "P4B result" and "P4B cause"). The short form asks only for what D2 needs. The full specification is the operator-approved
recap below; **build exactly this, nothing more.**

## Specification
1. **New desk schema `25.2`** and pilot arm `r25_sf`, both on the analyst tree. Each scenario (Base, Bull, Bear) declares:
   - `revenue_growth`: five values;
   - `earnings_margin`: five values, on the X basis.

   These replace `explicit_growth`, as 25.1 does (the 25.1 rules on when `explicit_growth` is still accepted carry over). All other
   revision-24 desk inputs stay unchanged: `long_run_margin`, `terminal_g`, `terminal_ronic`, `fade_years`, the rate, the frame,
   probabilities and crux.
2. **Removed from 25.2:**
   - the normalization block (`normalized_margin`, `normalization_horizon`, `structural_growth`, `normalized_revenue_base`, `flags`,
     `cycle_evidence`, `normalization_reason`, `reconciliation_reasons`);
   - every C1–C5 and K1–K4 check, together with its reason fields and loop guard;
   - the desk-call labels. The three classifications go back to the revision-24 written contract, as revision 24 has them.
   - The revision-24 written-report items (near-term and normalized earnings, the three labels) are kept exactly as in revision 24.
   - **Single pass:** no two-pass protocol.
3. **The desk arithmetic** for a 25.2 scenario is the 25.1 bridge's path arithmetic (R_t, m_t, κ, working capital on its own revenue),
   without the normalization derivation.
   - The near-term and normalized earnings that 25.1 derived come from the written contract, as in revision 24.
   - Find each 25.1 consumer of the derived normalization and say how 25.2 serves it: absent, with a stamp, never a fabricated value.
4. **Pack additions** (the facts owner is `pack_facts`; printed in the existing DEFAULTS or DATA area beside m5):
   - **The basis in plain words:** "earnings margin = net income plus after-tax amortization of acquired intangibles, divided by revenue;
     after interest and tax; not the operating margin".
   - **`x_margin_history`:** the X-basis margin per filed year, shown **with and without one-offs**. One-offs are the filed impairment and
     restructuring lines (GoodwillImpairmentLoss, AssetImpairmentCharges, ImpairmentOfLongLivedAssets…, RestructuringCharges and the
     equivalents the screener holds), added back after tax at the record's tax rate. Stamp the source of each. Where none are filed, say so.
   - **`x_margin_consensus_y1y2`:** the X-basis margin the consensus EPS levels imply for years 1 and 2, from the same quantities the
     DEFAULTS levels already use.
5. **The basis flag** (annotate, never refuse):
   - for each scenario's years 1 and 2, the ratio of the declared `earnings_margin` to `x_margin_consensus_y1y2`;
   - outside [0.67, 1.5]: the result and the verdict scorecard carry `margin_basis_gap` with the values. The desk message states the gap
     once, as information, not as a request;
   - no consensus: `no_basis_check_no_consensus`.

   The band is registered here, before any run.
6. **TASK text:** a 25.2 variant of item 3 that asks for the two lists and states the basis in the plain words above. A `PACK_REVISION` /
   arm revision for `r25_sf`. Record it in the comment log, following how `R25_REVISION` is handled; the operator gave perpetual approval
   for pack text, and the coordinator reviews.
7. **D2 stays off** (`d2_enabled` unset). This test is the analyst form only.

## Where
- **rs2:** a new branch `review-2026-10/short-form` from `8e2cb8a`, in the worktree `scratch/rev23/wt-short-form`. Commit by pathspec.
  Do not push.
- **Pilot:** mode `P4_SF=1` in `scratch/rev23/pilot_r25/`, mirroring `P4_BRIDGE`.
  - The names are MSGE, TASK and DAC, in that order, one run each.
  - Tree `tree_p4sf` at the short-form head.
  - Arm-`r25_sf` packs are **derived** from each name's revision-24 frozen pack, as `derive_arm_b` does. The derivation adds the new pack
    facts by recomputing them from that pack's own stored facts (no new collection).
  - Evidence and caches are copied from the P4 or P4_SET stores, never moved.
  - `score_p4sf.py` reports per name, against the same name's revision-24 run:
    - desk calls, refusals and loop markers;
    - minutes and the ratio to revision 24;
    - crux validity and citations;
    - each scenario's declared margins beside `x_margin_consensus_y1y2` and the history;
    - every `margin_basis_gap`.

## Tests
- **Unit tests** for 25.2:
  - acceptance of the two lists;
  - the removed fields are absent from the schema;
  - no C or K check runs;
  - the basis flag inside and outside the band, and with no consensus;
  - the one-off add-back;
  - 0.0 kept as a value.
- **Legacy unchanged:** every other arm's pack and desk result is byte-identical.
- **The full rs2 suite:** the same 42 failures by name as `8e2cb8a`.
- **The pilot tests** pass, with the other modes unchanged.

## Limits
- **Never launch** a model or use the GPU; the coordinator launches. Never touch Ollama.
- No edits to `frozen_p4`, `runs_p4` or `runs_p4b`.
- **Report (≤40 lines):**
  - commits and files;
  - test counts;
  - the derived packs' new facts for the 3 names;
  - the TASK diff summary;
  - ambiguities, each marked for a ruling.
