# CROSS_CHECK_Q rulings (Claude, 2026-10-30)

**Review:** `CROSS_CHECK_Q.md`, a fresh blind Opus review of `qwen_c/value` (`d2f3f15..03797d7`). Verdict: **REJECTED for E2 or any GPU
run.** Probes: `scratch/rev23/m3q/xcheck_q_probes/`.

**Verified by me before ruling:** findings 1, 3, 11, 13 and 22 re-ran with the reported numbers.
- V3 passed a 30% long-run margin with no quotes (value 27.43 against 16.73).
- The equity return through zero swings the value from +432 to −431.
- Scenarios without reasons pass at −15.62 per share.
- The V10 errors and the crashes reproduce.

**Correction of my own report.** RR_Q2_Q4 said the checks catch rev 26's recorded faults and that a clean output passes. True of the
fixtures, but the checks could be bypassed, and the fixtures did not test for that. I approved my own build unmeasured, the same error
as AUDIT_N6's v6.

**All 34 findings are accepted.** No GPU smoke, E2 or E3 runs until batches A–D are done and audited.

| # | Ruling | Batch |
|---|---|---|
| 1 | A reason counts only with ≥ 1 quote, every quote verified. V3's span must come from items other than [Y], of ≥ 2 distinct fiscal years: an item's period maps to the fiscal year that contains it, from the facts' fiscal-year ends. Proving that the quoted evidence reaches the premium level is not built; it is a stated limit, recorded under V3 | A |
| 2 | The investment path is a judgment input: its own supported reason, field validation, V3/V4 on each year's margin, and capex/revenue above the pooled ratio (a programme, not maintenance). O2c's per-year citation is that reason | A |
| 3 | Refuse `equity_ronic_not_positive` (RONIC_0 and RONIC_T after O5) | B |
| 4 | Reinstate O7's explicit-year capex input (mode 1: five values; mode 2: a year-5 target), stamped when uncited. Build `ppe` from the facts so the vintages rule runs, and stamp the pooled fallback. `investment_in_explicit_years` requires the override. Add an E1 production-path truth test. **Re-run the B1 rule on the production path under a new pre-registration (v1.3)**; B1 stands only if it passes there | D |
| 5 | A debt ladder (census-backed), refusing when none resolves while interest is filed; debt > 0 with no interest refused; kd band 1–20% (the audited rule). Revenue: per year, the largest of the revenue tags, plus a tag-switch level-break stamp. Shares reconciled to NI / diluted EPS within 5%, else `shares_scale_unverified` | C |
| 6 | Port rev 18's cash term: remove the after-tax interest on cash (cash × the bill rate) from the capitalized earnings, then add cash at face. With no bill rate: stamp, and do not add cash | C |
| 7 | Roll the value forward from the fiscal-year end to T at r, stamped with the stub (the doctrine; `1dcb3b2`) | B |
| 8 | companyfacts becomes a mutable prefix (refetched when online). Refuse `base_year_not_latest_annual` when the newest eligible annual filing's period is later than FY0 | C |
| 9 | K_0 = OI_0 − PT_0 − A_0 (filed pretax, so a tax anomaly cannot enter), stamped. V8: when ≥ 3 in-band years exist, use their median whenever the latest rate differs from it by more than 5 points | C |
| 10 | Bridge the long-run margin at `rev[5+H]` | B |
| 11 | Scenarios are validated with the Base rules, and each replacement needs its own supported reason | A |
| 12 | The reason for an input must address it: a keyword class per input (growth, margin, return, fade, terminal, investment), and one reason object cannot serve two inputs. This is partial (lexical) and stated as such | A |
| 13 | The V10 regex: handle negation ("not exceed", "no higher"), "record median", "N-year" and "historical" medians, and drop the bare "over" | A |
| 14 | V6 `cycle_position` from the true percentile (share of record years below the margin) | A |
| 15 | Every result carries `v5_withdrawn_status_unenforced` until the builder field exists. A builder field for withdrawn guidance goes on the 3Q list (it is versioned) | A (stamp) |
| 16 | V1 recomputes the levels flows independently from the inputs (not through `d2_flow`), and checks the Flow_0 identity against the filed base year | B |
| 17 | `family` is required, from the census; anything other than operating or commodity is `no_call` (`family_not_built`, utility, pre-profit, shell, financial until its task exists) | A |
| 18 | Stamp `per_share_basis_unverified` for foreign filers and ADS names until the ratio is wired. A split after FY0 is detected by the cover count against diluted shares (> 20%), and refused | C (stamp) |
| 19 | The amortization basis must be the same in every pooled year: use it only when amortization is filed for all pool years, else X = NI throughout | C |
| 20 | Stamp `leases_not_modeled` on every result (I_lessee +36.7% recorded as the known bias). L1 goes on the 3Q list | C (stamp) |
| 21 | RONIC_0 on tangible capital (equity + debt − cash − goodwill − intangibles), capped at 100%, stamped | C |
| 22 | `check()` never raises on model content: any exception in shape or assembly is `invalid` with the reason | A |
| 23 | `result.json` keeps every attempt's inputs, checks and values; the final status is the last attempt's, and earlier attempts are kept | A |
| 24 | `prepare` refuses a missing base-year operating income (`bridge_unavailable`) before any model call | A |
| 25 | Financial route: clean surplus with varying ROE. Fix when its task is built (not wired today) | later |
| 26 | Default: **price-blind**. The valuation prompt masks price, market cap and price-derived fields in [S0], as rev 26 ruled. Reversible; operator decision C5 | A |
| 27 | When the debt tag is a total (`LongTermDebt`), current debt is not added | C |
| 28 | Per fiscal year, the latest eligible filing first, then tag priority within it (the docstring's rule) | C |
| 29 | An undated leg (the loading) is stamped `coe_leg_undated` | B |
| 30 | A filed thereafter balance with A_5 = 0 runs off at the last positive schedule amount, stamped | B |
| 31–33 | Port the dropped stamps (`delta_pts` scale, partial history). The memo prints no reason V10 refused. The prompt pin covers the full user-message template. Tests: V2 and V5 cases, pass cases for V3/V7/V10, the production-path truth test, and the two tests that enshrined findings 12 and 19 rewritten | A/B |
| 34 | Carried. The sector loading already embeds sector-average leverage; a relevering rule needs its own test | carried |

**Order:** A (checks, robustness), B (desk), C (data and base), D (capex and B1 re-run). After each batch: the full suite, a commit, a push.
After D, a **fresh** blind cross-check before any GPU run.
