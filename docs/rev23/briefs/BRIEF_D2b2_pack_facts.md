# Brief D2b2: desk port part (b), rs2 side: pack facts that produce the `d2` members

## Read first
1. `docs/review_2026-09-22/rev23/PLAN_terminal_reinvestment.md`, these sections:
   - §3a, with its amendment;
   - §5: O3, O5 and O8;
   - the "Port part (a) audited" block at the end.
2. `docs/review_2026-09-22/rev23/REPORT_census_1a_addendum.md`: §1 (the routing rule) and §2 (δ without leases).
3. `briefs/BRIEF_D2b1_screener_fields.md`: the six new screener fields and their names. A parallel builder is adding them. Read them from
   the fundamentals row when present, and treat them as absent otherwise.
4. In the worktree, the comment block "THE d2 MEMBERS" in `tools/consensus_reference.py`, and `_d2_prepare` in
   `tools/audit_202608/financial_model_tool.py`.
5. Read these by grep and section, not whole files:
   - `capability_test.build_pack` (`facts = pack_facts.empty()`, `_lr_raw`, `owner_earnings_default_b`, `stub_months`, `quantize_long_run`);
   - `pack_facts`: `FACTS_VERSION`, `KEYS`, `SIDECAR_ONLY`, `write_sidecar`, `parity`;
   - `consensus_valuation.build_desk_context`;
   - `financial_model_tool.execute_financial_model`, including `_bridge_build`;
   - `throughcycle_record`: `tax_rate`, `earnings_detail`, `return_numerator`, `invested_capital`, `short_term_debt`;
   - `population_ranges.family_for` and `sic_family`.
6. These scratch scripts are references for the measurement. **Do not import them:**
   - `scratch/rev23/terminal_d2/census_1a.py` `measure`;
   - `census_1a_addendum.py` `route`;
   - `phase4_restore/o5_check.py`.
7. `rs2-local/AGENTS.md`.

## Workspace and limits
- **Worktree:** branch `review-2026-10/d2-facts` from `1dcb3b2` (part (a)):
  ```
  git -C C:/Users/riper/stocks/rs2-local worktree add -b review-2026-10/d2-facts ../stocks-workspace/scratch/rev23/wt-d2-facts 1dcb3b2
  ```
- **Commit by pathspec.**
- **Never:**
  - push, merge or deploy;
  - use the GPU or make model calls;
  - edit `.env*` or config defaults;
  - use a bare `git stash`.
- **No change to anything the model reads.** No pack text, TASK, tool schema or `PACK_REVISION`; those belong to part (c). `d2` is a
  facts member that is `SIDECAR_ONLY` and never rendered to the model.
- **Your report is at most 50 lines.**

## Build
1. **`facts["d2"]`, computed in `build_pack` from filed data.** The members and their sources:
   - **`family`:** `"financial"` by the census addendum's balance-sheet rule (§1), carried into rs2 code (no import from scratch);
     otherwise `"operating"`. Where the rule needs a field the store lacks, use `"operating"` and stamp `family_route_unresolved`.
   - **`delta`:** non-lease debt divided by (non-lease debt + market cap), using the pack's price and diluted shares.
     - Non-lease debt is the debt that `throughcycle_record.invested_capital` uses (leases excluded), net of cash, floored at 0, per
       `census_1a.measure`.
     - Market cap and debt must be in one currency. If they are not, the member is absent, stamped `delta_currency_unproven`.
     - A financial-route name takes no δ.
   - **`kd`:** (interest expense − lease interest) / non-lease gross debt, with interest expense being `interest_on_borrowings` if present,
     else `interest_expense`. Absent when debt is 0 or unproven. Never default it to 0.05.
   - **`tau`:** `throughcycle_record.tax_rate` for the base year.
   - **`pooled`:** five-year raw totals over the base year and the 4 before it:
     - revenue, capex, lease_principal and rou_dep;
     - **da_org = da − rou_depreciation − amortization_intangibles,** taken per year and then summed;
     - `years` = the number of years present.
     A missing component year is stamped by name. 0.0 is a value: never use `or`.
   - **`ppe`:** gross_prior and gross from `ppe_gross`, net from `ppe_net`, da_org_0. Absent when `ppe_gross` is not filed.
   - **`amortization`:** `{schedule, thereafter}` from the base-year filing's `amortization_schedule` when all five years are present;
     else `{a0}` from the base-year `amortization_intangibles`; else absent.
   - **`year0`:** the base-year capex, da_org, dnwc (from the record's NWC), lease_principal, rou_dep, amortization and invested_capital.
   - **`reserves` and `reit`:** absent in this part (O8: diagnostics only; parsing reserves is off the critical path). The desk stamps them
     `unavailable`.
   - **`valuation_date`:** the pack's as-of date.
   - **Each member's source and stamps** go in a sibling `facts["d2_provenance"]`. When a required member cannot be measured, `facts["d2"]`
     is null and `facts["d2_unavailable"]` lists the members by name. Never fill a value silently.
2. **L3 for D2 only.** `long_run` gains `r_tc_after_lease_interest` (the return numerator with interest − lease_interest), beside today's
   `r_tc`. Today's `r_tc`, `base_cf` and every legacy fact are unchanged; L2 is superseded under D2, because base_cf is not read there.
   Record this as an ambiguity for a ruling.
3. **Bump `FACTS_VERSION` 11 → 12,** with a changelog entry. Add `d2`, `d2_provenance` and `d2_unavailable` to `KEYS` and
   `SIDECAR_ONLY`, so the sidecar and parity carry them.
4. **The context forwards; the desk call does not use it yet.** `build_desk_context` carries `d2`.
   - `execute_financial_model` forwards it to `unbundled_dcf(d2=...)` only when the context's `d2_enabled` is true. No arm sets that,
     so production behaviour is unchanged.
   - With `d2_enabled`, the RONIC start (`long_run["r_tc"]` passed to the desk) is `r_tc_after_lease_interest` when present.

## Tests (system Python, `tests` and `tools/audit_202608/tests`)
1. **Legacy unchanged:**
   - every pack fact other than the new keys is identical on a fixture pack;
   - the replay-parity test passes with the new keys;
   - with `d2_enabled` unset, the desk result is identical.
2. **Measurement:** unit tests for each member from constructed fundamentals rows. They must cover:
   - IFRS lessee, US GAAP finance lessee, no leases;
   - net cash (δ = 0);
   - a currency mismatch, which leaves δ absent;
   - the financial route;
   - partial history;
   - the schedule versus a0 fallback;
   - 0.0 kept as a value.
3. **End to end without the GPU:** on stored pack inputs for MSGE, BUD and DAC (if fixtures exist; else the closest stored fundamentals
   rows), build `facts["d2"]` and run the desk with `d2_enabled`. Report value per share against legacy, with every stamp. These are
   observations, not pass/fail; never a target.
4. **Full suite:** the same 42 known failures by name as `1dcb3b2`.

## Report
- commits;
- files, one line each;
- test counts;
- the end-to-end table;
- ambiguities, each marked for a ruling.
