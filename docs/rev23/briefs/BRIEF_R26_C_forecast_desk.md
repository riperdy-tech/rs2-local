# Brief R26-C: `submit_forecast`, the path builder, the operating-to-X bridge, the alternative paths, K = 3 aggregation and the pull ratio (SPEC revision 26, sections 2–3)

**Read first:**
- `docs/review_2026-09-22/rev23/SPEC_rev26_staged_analyst.md` (all of it; sections 2 and 3 are yours);
- `rs2-local/AGENTS.md`;
- in `tools/audit_202608/financial_model_tool.py`: desk schema 25.2 (`DESK_SCHEMA_252`, `_bridge_build`, the path arithmetic) and the
  price-implied solver;
- `tools/x_margin_basis.py`.

**Where:** rs2 branch `review-2026-10/r26-desk` from `6bc2ad0`, in the worktree `scratch/rev23/wt-r26-desk`.
- New module `tools/r26_forecast.py`, plus the smallest hook into the desk.
- Commit by pathspec. Do not push.
- Never use the GPU, Ollama or a model; no `.env*`; no bare `git stash`.
- **Every existing desk result must stay byte-identical.**

**Build (pure functions, deterministic, documented):**
1. **`validate_forecast(obj)`:** structure only, per SPEC section 2.
   - Returns named problems: fields, finiteness, enums, fact IDs present in the supplied dossier.
   - Numbers are never bounded.
2. **`build_path(forecast, op_margin_bar, rev0)`:**
   - years 1–5 of revenue growth and operating margin;
   - the normalized margin = the bar's baseline value + `delta_pts`;
   - transitions `linear`, `step_at_year` and `hold_then_linear` exactly as written in SPEC section 2, with a worked docstring example for
     each.
3. **`bridge_to_x(path, facts)`:**
   - the per-year X margin by the SPEC formula, with its inputs;
   - net interest is the base-year filed dollars, held; other non-operating is 0, stamped; τ is measured, else `bridge_unavailable_tax`;
   - A_t from the filed schedule, else A_0 held, stamped;
   - returns the table and the assumptions;
   - **`invert_bridge(x_margin, year, facts)`** gives the operating-basis equivalent (for R26-B's consensus).
   - The financial family is an identity: margins are already on the X basis.
4. **`value_forecast(...)`:** feeds the X-margin path and revenue into the 25.2 path arithmetic (call the existing desk with
   `desk_schema = 25.2`-style bridge inputs; do not re-implement the DCF), with `long_run_margin` bridged at the final year.
5. **`alt_paths(forecast, dossier, ...)`:** for each cited fact with a finite `duration_years`, the alternative path and value of SPEC
   section 2, step 4. Never substituted.
6. **`aggregate(samples)`:**
   - the median index (Base value);
   - `spread = (max − min) / median`;
   - `direction_split(samples, price_band)`: true when samples straddle the verdict boundary, using the existing band rule.
7. **`pull_ratio(m_pre, m_post, m_consensus)`:** null when consensus is unavailable, or when `m_consensus == m_pre`.

**Tests:**
- each transition, with exact numbers;
- the bridge, against a hand-computed MSGE-like case, including the A_t and tax-unavailable branches;
- `invert_bridge` round-trips `bridge_to_x`;
- the alternative path with a 4.7-year fact;
- the aggregation and direction split;
- pull-ratio edge cases;
- 0.0 kept as a value;
- the full rs2 suite: the same 42 failures by name as `6bc2ad0`.

**Report (≤30 lines):** commits, files, test counts, the bridge table for a worked example, and ambiguities.
