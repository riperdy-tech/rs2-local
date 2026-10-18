# Terminal-reinvestment harness (steps 1, 3 and 5 of PLAN_terminal_reinvestment.md)

The code behind `REPORT_synthetic_baseline_terminal.md`, `REPORT_step2_lease_audit.md`, `REPORT_step3_reference_d2.md` and
`REPORT_step5_sustaining_charge.md`. These are copies for review; the working copies are in the operator's local scratch.

| File | What it is |
|---|---|
| `synthetic.py` | The simulator: firms A–I (plus B2, C2, C3) built from their own economics. Each firm has capacity bought in vintages, straight-line depreciation, working capital, tax, a debt policy, acquired-intangible amortization, IFRS 16 leases and impairment. The true value is a 300-year DCF of each firm's own equity cash flows. It also feeds today's desk the ideal analyst's inputs. |
| `reference_d2.py` | Design D2 as specified in the plan's §3a, written independently of the desk. `d2_value` is the default path (gap fading over F); `d2_value_state` is the O2c path (levels through a cited investment state). The D&A rules are `pooled`, `uniform`, `ppe` and `vintages`; the τ·A run-off is `amort_path`. |
| `synthetic_baseline.json` | Today's desk on every firm (`python synthetic.py`). |
| `reference_d2.json` | D2 on every firm (`python reference_d2.py`). |

**Dependency.** "Today's desk" is `tools/audit_202608/financial_model_tool.unbundled_dcf` of rs2-local at `review-2026-10/rev25-bridge`
`9ed16fc`, imported read-only. `synthetic.py` points at a local worktree of that commit (`WT` at the top). To run it elsewhere, check out
that commit and change `WT`. `reference_d2.py` imports nothing of rs2-local.

## Reproducing the reports' numbers

```
python synthetic.py --self-test          # simulator identities (capital roll-forward, steady-state growth, value driver on firm A)
python synthetic.py                      # step 1 baseline table
python synthetic.py --lease-variants     # step 2, firm I: today / base_cf less lease principal / plus the return after lease interest
python reference_d2.py                   # step 3 part 1 table
```

Step 3 addenda and step 5 (the reports' other tables) come from calls like:

```python
import reference_d2 as D
t = D.truth("E_holiday")["value"]
D.d2_value_state("E_holiday", 9, "vintages")["value"] / t - 1     # E, levels to year 14, vintages D&A
D.d2_value("C3_impaired", "true", "vintages")["value"] / D.truth("C3_impaired")["value"] - 1
D.d2_value("A_compounder", "true", "vintages", s=0.1597)          # step 5: the filed sustaining measure applied to firm A
```

Interpreter used: CPython 3.12, standard library only (plus rs2-local's own modules for the desk comparison).
