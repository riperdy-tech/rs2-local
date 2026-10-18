# Brief D2a: the desk port, part (a): the D2 formula in the desk (terminal reinvestment, O7, O5, O2c, O8)

## Read first, in this order
1. **`docs/review_2026-09-22/rev23/PLAN_terminal_reinvestment.md`:**
   - §3: D2;
   - §3a, with its amendment: the O7 levels leg, the D&A vintages rule, τ·A, O2c;
   - §5: O3 (financials), O5 (δ), O8 (no s, binding).
2. **`scratch/rev23/terminal_d2/reference_d2.py`:** the reference that you must match to machine precision.
3. **`scratch/rev23/terminal_d2/synthetic.py`:** the simulator. It is desk-free now; `desk()` imports the desk lazily.
4. **`rs2-local/AGENTS.md`.**

Read code by grep and section. Your report is at most 50 lines.

## Workspace and limits
- **Worktree:** `git -C C:/Users/riper/stocks/rs2-local worktree add -b review-2026-10/d2-port ../stocks-workspace/scratch/rev23/wt-d2-port 8e2cb8a`
  (`8e2cb8a` is the analyst tree's head: `ollama_raw` plus the crux message fix).
- **Commit by pathspec.**
- **Never:** push, merge or deploy; use the GPU or make model calls; edit `.env*` or config defaults; use a bare `git stash`.
- **No pack or TASK changes** in this part; those are parts (b) and (c).

## Build
1. **The D2 path in `financial_model_tool.unbundled_dcf`** and `consensus_reference.long_run_value`, driven by **new optional long-run
   members**. Name them in one place, documented, for example `d2`:
   - pooled `capex_ratio` and `da_org_ratio` (sums over five years, raw totals carried);
   - the vintage inputs (gross PP&E, net PP&E, D&A_org at the base);
   - `delta`, measured leverage, non-lease debt at market weights;
   - the lease `P` and `ROU` ratios;
   - the amortization schedule `A_1..A_5` and its "thereafter" balance, with tax τ;
   - an optional analyst capex override (mode 1: five values; mode 2: a year-5 target), with an optional cited path of H years beyond year 5.
2. **When `d2` is absent:** the desk is **byte-for-byte today's.**
3. **When present:**
   - **years 1–5:** Flow_t = X_t − (1 − δ)(capex_t − D&A_org,t + ΔNWC_t) − (P_t − ROU_t) + τ·A_t;
   - **the year-5 wedge:** w_5 = (I_5 − I*_5)/R_5, with I*_5 = (g_6/RONIC_0)·E_5 (**no S: O8**);
   - **the fade:** Flow_t = E_t(1 − g_{t+1}/RONIC_t) − w_t R_t, with w_t fading over F;
   - **O2c:** the levels leg runs to 5 + H, then the funded path. N = 5 + max(F, H);
   - **the terminal:** E_{N+1}(1 − g_T/RONIC_T)/(r − g_T). **There is no s anywhere in the production code.** A test-only copy may keep
     it, to reproduce step 5.
4. **Financials (O3):** a route selected by a member, `family = "financial"`. Flow_t = E_t(1 − g_{t+1}/ROE_t) from year 1; no capex, D&A
   or working capital.
5. **Positivity:** E_0 ≤ 0 is refused. A negative flow year is valued.
6. **The diagnostics of §3** (stamped on the result, never changing a value):
   - `rho_5_bridge` and `wedge_rate_5`;
   - the implied return of the explicit years (`negative_net_reinvestment_explicit` when Σ I ≤ 0);
   - the clean-surplus roll-forward ROIC_{N+1}, set against RONIC_T and r_tc;
   - the seam ratio;
   - the steady-state capex/D&A;
   - the O8 diagnostics `fd_vs_dda_gap` and `reit_recurring_capex_vs_da`, computed only when their inputs are supplied, else stamped
     `unavailable`, never as "no gap";
   - `capex_override_uncited` when an override has no citation.

## The tests (the regression gate)
Use the system Python per AGENTS.md; all must pass.
1. **Legacy:**
   - with `d2` absent, every existing test passes unchanged;
   - plus a test that s = 0, w = 0 and δ = 0, supplied through `d2` in the legacy-equivalent form, reproduce today's value **to the cent
     and to 1e-6 relative.**
2. **Synthetic parity:** for every firm (A, B, B2, C, C2, C3, D, E, F, G, H, I), feed the desk the `d2` members computed from the
   simulated statements, on each firm's registered path.
   - **The desk's value and every annual flow** must equal `reference_d2.py`'s to 1e-9.
   - Read the reference results **in place** from `scratch/rev23/terminal_d2/`, resolved through `STOCKS_ROOT`, never an absolute path;
     skip if absent.
   - **Report C and C2 twice:** the default fade (expected to fail ±3%: +7.37%, +4.53%) and the cited path. Never count the cited pass as a
     default pass.
3. **The O2c states of H:** missing, cited, uncited, malformed, and H > F.
4. **No hidden charge:** supplying or removing the reserve and REIT diagnostic inputs changes **no** value or flow.
5. **The identity:** Flow_0 = X_0 − (1 − δ)(capex_0 − D&A_org,0 + ΔNWC_0) − (P_0 − ROU_0) + τ·A_0, to 1e-9.
6. **The full suite:** the same 42 known failures by name as `2b799bd`.

## Report
- commits;
- files, one line each;
- test counts;
- the synthetic parity table (firm, desk error, reference error, the largest annual-flow difference);
- ambiguities, each marked for a ruling.
