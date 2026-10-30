# WO_Q5: the `valuation_inputs` task, checks V1–V10 and the code memo (SPEC_m3q §2, §4), 2026-10-30

**Branch:** rs2 `review-2026-10/m3q` (worktree `scratch/rev23/wt-m3q`).

**Done before this WO:**
- `qwen_c/value/desk.py` and `facts.py` (`c6da688`);
- `inputs.py` (the code-owned base, V8 tax, the operating-margin bridge).

**No GPU, no prompt run.** Everything here is tested on canned model outputs.

## 1. What the model returns (one JSON object, task `valuation_inputs`)

```
{"task": "valuation_inputs",
 "base": {
   "rev_growth":   [g1, g2],                      years 1-2, fractions
   "op_margin":    [m1, m2],                      years 1-2, GAAP operating margin (the filed basis)
   "normalized":   {"year": 3..5, "baseline": "min|p25|median|p75|max|last", "delta_pts": d, "rev_growth": g},
   "transition":   "linear|step_at_year|hold_then_linear",
   "fade_years":   F (1..30),
   "long_run_op_margin": m_L,
   "terminal_ronic": RONIC_T (> 0, or "unlimited"),
   "terminal_g":   g_T,
   "margin_source": "record|pricing_or_mix|investment_in_explicit_years|investment_after_year5|decline",
   "investment_path": null | [{"year": t, "capex_over_revenue": c, "revenue_growth": g, "op_margin": m}] (O2c; years 6..5+H)},
 "bear": {same keys, any subset, as replacements}, "bull": {...},
 "prob": {"bear": p, "base": p, "bull": p},
 "reasons": [{"input": "<path, e.g. base.normalized.delta_pts>", "claim": "...", "fact_ids": [...], "quotes": [...],
              "numbers": [...], "confidence_basis": "..."}],
 "unknowns": [...]}
```

- Every judgment input in `base` must have at least one reason whose `input` names it. A scenario replacement needs its own
  reason.
- Reasons are claims under `contract.check_claim` (contract v3): the quotes are verified in the packet and the numbers are
  listed. A reason is supported only if `check_claim` returns `supported`.
- The code memo (`memo.py`) prints the numbers. The model writes no table.

## 2. The checks (`qwen_c/value/checks.py`)

**Repair rule.** A **contract** failure makes the named input *unsupported*. The task gets one repair turn listing the
failures. If the input is still unsupported, the valuation is `valuation_incomplete` with the reasons. No input is replaced
by a code value.

**Annotations** ride on the result and gate nothing.

| # | Kind | Rule (exact) |
|---|---|---|
| V1 | contract | **Shape and finiteness:** probabilities ≥ 0 summing to 1 ± 0.01; F in 1..30; g_T < r (the code's cost of equity); RONIC_T > 0.<br>**After computing, recompute:**<ul><li>revenue × margin = X per year;</li><li>levels flows by `d2_flow`;</li><li>PV sums;</li><li>value per share = (equity + excess cash) / shares within 1e-9.</li></ul> |
| V2 | annotation | `flow_seam_out_of_band`: the year-6 / year-5 flow ratio outside [0.67, 1.5] with `investment_path` null |
| V3 | contract | `unsupported_premium`: the normalized or long-run operating margin is above the filed record maximum or below its minimum (`inputs.base(...)["record"]`, the last ≥ 5 fiscal years). It needs a supported reason on that input citing at least one item that is a filed statement or a filed annual or quarterly section, and whose quotes span facts of ≥ 2 distinct fiscal years.<br>A half-year, one peak year or guidance alone fails |
| V4 | contract | **Basis:** a reason for `op_margin`, `normalized` or `long_run_op_margin` must cite at least one statement item (kind `statement`) or filed section. Company-adjusted or third-party items may be cited as well, never alone |
| V5 | contract | **Period and status:** every cited item's effective time ≤ T (already true of any packet item). An item the packet marks `withdrawn` or `superseded` cannot be cited |
| V6 | code-owned | **Labels.** `cycle_position` = the percentile of the normalized margin in the filed record (< 33 trough, 33–67 mid, > 67 peak). `margin_persistence` = sign(m_L − record median). The growth trajectory is from the path. Any label the model writes is kept as `*_submitted`, and a mismatch is annotated |
| V7 | contract | **Decliner terminal:** Base revenue growth < 0 in at least two of years 1, 2 and normalized, with g_T > 0, needs a supported reason on `terminal_g` |
| V8 | code-owned | **Tax:** `inputs.tax_rate` (done) |
| V9 | contract | **Scenario order:** Bear ≤ Base ≤ Bull on each replaced growth, margin and RONIC_T input, unless that input's scenario reason is supported. Values must be monotone after computing (V1) |
| V10 | contract | **Reason direction:** a reason whose claim says "above / below / higher / lower than the median (or record, or last year)" must agree with the input's position against that reference, computed by code. A contradiction makes the input unsupported. The memo's numbers and labels come only from code |
| V11 | contract | `fade_margin_investment_after_year5` (RR_Q3 §5–6): `margin_source = investment_after_year5` needs a non-null `investment_path`. A margin rise above the year-5 margin with `margin_source` of `record` or `decline` is a contradiction |

## 3. Tests (canned outputs)

- Each of rev 26's recorded faults, rebuilt as a fixture, must fail its check:
  - DAR's adjusted EBITDA as the only basis (V4);
  - MSGE's 14.0% against a 13.5% record maximum with no span (V3);
  - ITGR's withdrawn outlook (V5);
  - VSNT's positive g_T while shrinking (V7);
  - DAC's "below the median" with the input above it (V10).
- A clean output passes every check.
- Every check has a pass case and a fail case.
- `0.0` inputs are values.
- Suite run: `"C:\Program Files\Python312\python.exe" -m pytest qwen_c/tests -q` (never while a sweep writes `cache/`).

## 4. Not in this WO

- The prompt text (`m3m.prompt.v4`) and the runner wiring: WO_Q5b, after checks.py is audited. The other tasks' SYSTEM and
  task texts stay byte-identical, which is tested.
- The cost of equity: the code anchor port. It needs the MRI anchors path (`MRI_ANCHORS_DIR`); WO_Q5b.
