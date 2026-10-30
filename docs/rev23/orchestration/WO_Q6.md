# WO_Q6: the financial route's valuation task (banks, insurers, mortgage REITs), 2026-10-30

**Why.** 20 of the 156 census names are financial. 13 have a measured base (`inputs.base_financial`), and all 20 are refused by the
runner today (`family_not_routed`). O3 (retained equity) and O6 (mortgage REITs) are approved.

**Done already:**
- `inputs.base_financial`: the book-equity driver;
- `desk.value_financial` v2: the clean-surplus identity with varying ROE, driver `book` (`d6ff468`).

## 1. What the model returns (task `valuation_inputs_financial`, prompt `m3q.prompt.fin.v1`)

```
{"base": {"book_growth": [g1, g2], "roe": [r1, r2],
          "normalized": {"year": 3..5, "baseline": "min|p25|median|p75|max|last", "delta_pts": d, "book_growth": g},
          "transition": "linear|step_at_year|hold_then_linear", "transition_year": null,
          "fade_years": F, "long_run_roe": ROE_T, "terminal_g": g_T},
 "bear": {...}, "bull": {...}, "prob": {...}, "reasons": [...], "unknowns": [...]}
```

- ROE is on opening book equity.
- The baseline statistics are the filed ROE record, from `base_financial["record"]["roe"]`.
- There is no capex, D&A, working capital or investment path: O3 has none.

## 2. Code (reuse, not a parallel engine)

- `forecast_fin.assemble(sc, b, bar, r)` builds the book path R_1 = filed FY0 closing equity, R_{t+1} = R_t (1 + g_t), with the
  ROE path from the same `_blend` rules. It calls `desk.value_financial(..., driver="book")` and rolls forward to T as the operating
  route does (`stub_days`).
- `checks`: one route parameter. The margin rules apply to ROE against the ROE record:
  - V3, V3g, V4, V9 and V10 with the same quote and span rules;
  - V7 on book growth;
  - g_T against the anchor;
  - `ronic_not_above_growth` (ROE_T > g_T).
- V11 and the capex/investment rules do not apply.
- The keyword classes are extended for ROE, book and capital.
- [V0] for a financial prints the ROE record, book equity, tax and cost of equity.
- The runner routes `financial` (and `mortgage_reit` when the census has it) to this task. Every other family stays a no_call.

## 3. Tests and acceptance

- **Truth:** `F_insurer` through the production path (facts → base_financial → assemble → desk) within ±3%. A new truth firm,
  `F2_bank` (ROE rising from 9% to 12% over 5 years, book growth 6%), is pre-registered before the run.
- **Check fixtures:** each of V3, V4, V7, V9 and V10, with a pass and a fail case on ROE.
- **Coverage re-run** on the 20 financials.
- **Review:** a fresh blind cross-check before any GPU run, time-boxed as CROSS_CHECK_Q2_RULINGS states.

## 4. Not in this WO

- Insurer reserve adequacy and bank capital constraints (CET1). They are stamped `capital_constraint_not_modeled`.
