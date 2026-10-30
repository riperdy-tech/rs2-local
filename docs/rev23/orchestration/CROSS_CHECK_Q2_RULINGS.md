# CROSS_CHECK_Q2 rulings (Claude, 2026-10-30)

**Review:** `CROSS_CHECK_Q2.md`, the second blind review, of `03797d7..5fe8e91`. **Verdict: REJECTED for E2; the GPU smoke may run
for mechanics only.** Probes: `scratch/rev23/m3q/xcheck_q2_probes/`.

**Governing rule.** The operator's guidance (2026-10-30): "we can't and don't need to be perfect." A finding is fixed when it could
change a decision, or when it is a bypass, an identity error, point-in-time leakage or a silent default. Otherwise it is stamped with
its known size and carried. **This is the last full review cycle before the smoke.** After the fixes I re-run the review's own probes
myself. There is no third full review unless a probe fails.

| # | Ruling | Kind |
|---|---|---|
| N1 | A period after the last filed fiscal year maps to the next fiscal year: FY0 + one year, the year that 10-Q sits in. A test on a real stored-packet layout (the FY0 10-K plus the later 10-Q) | fix |
| N2 | V3's span counts only the items whose quote is verified, and never [Y] items | fix |
| N3 | V7: when Base shrinks and g_T > 0, the terminal_g reason must use a return-to-growth word (grow, recover, rebound, return to growth, expand), not decline words | fix |
| N4 | V3, V4 and V10 run on every scenario's margin inputs too. A per-share value ≤ 0 in any scenario is annotated `value_not_positive` | fix |
| N5 | V10 scans every margin reason (Base and scenarios, years 1–2 included), and the regex adds "N year", "seven-year" and "historical average". A reason that names a specific year (e.g. "the 2024 margin") is skipped, not refused | fix |
| N6 | A capex path below the filed record's minimum capex/revenue (pooled years), or above its maximum, needs a supported reason spanning two filed fiscal years (V3's rule applied to capex). Otherwise the input is unsupported | fix |
| N7 | Annotate `terminal_g_above_anchor` when g_T > the MRI long-run growth anchor, and `terminal_spread_thin` when r − g_T < 0.02. Any bound beyond an annotation needs a SPEC ruling, carried as decision B13 | fix (annotation) |
| N10 | δ = net debt (debt − cash − short-term investments, floored at 0) over net debt + market cap, as approved in O5. Finance leases are counted in debt only through the total tags that include them, stamped `debt_includes_finance_leases` when such a tag is used | fix |
| N8 | The vintages D&A rule is used only when its implied asset life is in [5, 40] years and its year-5 D&A/revenue is within ±50% of the pooled ratio. Otherwise pooled, stamped `da_vintages_out_of_bounds`. D&A_org for the life always excludes filed amortization. [V0] prints the D&A path the desk uses. The truth-test firms cannot tell the rules apart (stated); a decaying-D&A truth firm is carried to the B12 pre-registration | fix (bounds) + carry |
| N9 | When NCI is above 10% of pretax income, stamp `nci_material`; above 25%, refuse `nci_dominant` (the K_0 dollar hold is not valid then) | fix |
| N11 | A V1 AssertionError in `run.value` writes result.json with status `engine_defect`, and does not crash | fix |
| N12 | `prepare` refuses a stub above 800 days (`base_year_too_old`) before any model call | fix |
| N13 | A zero or negative revenue year in the pool is refused (`revenue_not_positive`) | fix |
| N14 | Absent goodwill, intangibles or short-term investments are stamped `<concept>_not_filed_taken_as_0`; a filed EPS of 0.0 counts as not filed for the share check | fix (stamps) |
| N15 | The share check accepts an absolute difference ≤ $0.006 (EPS rounding to the cent) | fix. If-converted diluters stay refused: carried, stamped in the refusal text |
| N16 | result.json carries the base's stamps and a per-concept summary of the facts stamps | fix |
| N17 | V11 gets a 0.0005 tolerance; the keyword classes stay lexical (ruling 12), and a false refusal shows in the repair turn | fix (tolerance); keywords carried |
| #2 | The investment path's growth: annotate `investment_path_growth_above_record` when it exceeds the filed record's maximum revenue growth | fix (annotation) |
| #16 | V1 does not recompute the fade years. The fade arithmetic is parity-tested to 1e-9 against the reference. Carried | carry |
| #18 | Split detection: not built. US filers are stamped `split_after_fy0_unchecked` | stamp |
| #19 | The X = NI fallback departs from the O7 amendment (hold A_0, stamped). Kept: it is consistent and conservative (no shield without the add-back). Recorded as a deviation | carry |
| #27 | `LongTermDebt` used as the total while `LongTermDebtCurrent` is also filed: stamp `debt_total_tag_ambiguous` (MTCH) | stamp |
| #34, #25, V2 test | Carried | carry |
| E2 | **E2 is descoped.** At T 2026-10-15 at most 2–4 of the 12 consumed names can be valued, and none of the fault names (MSGE, DAC, VSNT) can run, so E2 cannot measure what it was for. It is replaced by the smoke (S1–S3, on TASK or DAR, labelled mechanics-only) and the check fixtures. Evaluation moves to E3 (prospective). This falls under B5 (regression set only), which the operator ruled | ruling |

**Smoke conditions (adopted):**
- **S1:** TASK or DAR only, never an E3-eligible name.
- **S2:** labelled `mechanics_only`; no evidence for E2 or E3.
- **S3:** read for the parse rate, the repair turn, the prompt length and result.json.

## Done (2026-10-30, rs2 `1aa8340`; suite 568)

Every "fix" row above is implemented. The reviewer's probes were re-run against the fixed code: `p_checks`, `p_checks2`, `p_run`,
`p_desk`, `p_delta_nci` and `p_vint_amort`.
- **Confirmed:**
  - the no-quote and half-year V3 bypasses are refused;
  - scenarios are checked, and a negative value is annotated;
  - an investment path at 40% with no reason is refused;
  - V6 uses the percentile; V1 catches an explicit-year engine defect;
  - malformed replies are `invalid`;
  - the routing, the cash term (+$9.82 a share for $100M at face) and the vintages bounds behave as ruled.
- **Three material inflations the re-run exposed, fixed in the same commit:**
  - **V3g:** revenue growth above the filed record's maximum needs a two-fiscal-year span. An investment path at 15% or 30%
    growth (+130% / +552%) is now unsupported.
  - **V3g:** terminal growth above the MRI long-run growth anchor needs a two-fiscal-year span. g_T 5% / 8.9% is now unsupported;
    3% passes.
  - **Desk:** `ronic_not_above_growth`, the long-run equity return must exceed g_T. The near-zero equity-return explosion
    (−431) is now refused.
- **Carried, as ruled:**
  - #16 (V1 does not recompute the fade; a +3.9% fade defect passes);
  - the if-converted share refusal (CHEF);
  - #18, #19, #25, #34.
- **Next:** the GPU smoke under S1–S3, on TASK or DAR. The time box holds: no third full review unless the smoke shows a defect.
