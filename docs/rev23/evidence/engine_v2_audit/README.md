# D-T1 / D-T3 evidence (SPEC_rebuild AK.19 rule, AK.20 result, AK.21 publication)

- `d_t1_residuals_cut2025.csv.gz`: the vintage-2024 residual panel (outcomes filed before 2025-01-01), 43,176 rows of cik, date, family,
  variable, year and residual (derived from public SEC filings). Exported by `export_residuals.py` from rs2-local branch
  `review-2026-10/gate2-run2` at `a605eff` (`valuation/priors_build/near_term.residual_frame`).
- `d_t1_from_csv.py`: recomputes D-T1 from that file alone (numpy and pandas; imports nothing from rs2-local):
  `python d_t1_from_csv.py d_t1_residuals_cut2025.csv.gz`.
- `d_t1_tails.py`: the original run on the build's own residual frame, plus D-T3; its output is `d_t1_tails_result.json`.
- `d_t1_check.py`: an independent Monte Carlo check of the Gaussian rates, and the t(nu=4) implied rates that led AK.20 to withdraw t4.

These scripts ran from `stocks-workspace/scratch/rev23/engine_v2_audit/`. stocks-workspace has no remote, so its commit hashes
(for example `735fcb9`) do not resolve in this repository. The local paths in the scripts point at that layout.
