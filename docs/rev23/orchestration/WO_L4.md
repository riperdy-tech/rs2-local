# WO_L4: Factor-stage deterministic replay of run 40608600897

- **Milestone and gate:** 3L, gate L-P4F.
- **Executor:** Claude.
- **Issued:** 2026-10-29. The scope and tests below were fixed before the build started.

## Goal

Rerun `scripts/score_factors_dual_door.py`, at the run's `head_sha` `ebcdda43`, on the run's input bytes. Then compare
its two outputs with the published blobs in output commit `9046be40`. A match shows the published nomination is a
deterministic function of the preserved inputs. A mismatch is diagnosed down to the input or code that causes it.

## Inputs

These follow WO_L3's input classification (`m3l_verifier/out/40608600897.json`):

| Inputs | Taken from |
|---|---|
| `HEAD_TREE` inputs, and `PREVIOUS_OUTPUT` `factor_scores.json` | `head_sha` blobs |
| `IN_RUN_COMMITTED` inputs: `stocks.json`, `price_history.json`, `tier1_hygiene_survivors.json` | output-commit blobs |
| `momentum_state.json` (`IN_RUN_UNPRESERVED`) | the `head_sha` blob. **This is a known substitution**, because the in-run bytes were not committed. The output records `momentum_price_asof` 2026-10-27, the same date as the `head_sha` copy, so equality is possible but not guaranteed. |
| Code | `scripts/` at `head_sha` |

## Environment

- **MRI:** `MRI_OUTPUTS_DIR` points to a path that does not exist, so the run's `COMMITTED_SNAPSHOT` branch is
  reproduced.
- **Clock:** `datetime.now` in the scorer module is frozen at 2026-10-28T00:59:44Z, the scorer start time in the log.
  It is used only for age arithmetic and `generated_at`.
- **Python:** system 3.12. The runner used 3.11.17, and the scorer is pure standard library.
- **Hash seed:** run twice, with `PYTHONHASHSEED=0` and `PYTHONHASHSEED=12345`, to expose any dependence on set order.

## Scope

- **Create only** `stocks-workspace/scratch/rev23/m3l_replay/`: `replay_factor_stage.py`, `out/`, plus a temporary
  working tree under the session scratchpad.
- **No changes to any repository.** No network, no GPU.

## Acceptance

- Both outputs are equal to the published blobs after removing only the declared time fields (`generated_at`), compared
  as parsed JSON. The byte comparison is reported as well.
- If they are not equal, report:
  - the differing JSON paths, counted and sampled;
  - whether every difference traces to the substituted `momentum_state.json`, shown by the momentum fields of the
    differing tickers.

  In that case the gate result is `NOT_REPRODUCIBLE_UNPRESERVED_INPUT`, and the fix is a request to the operator: add
  `momentum_state.json` and `daily_closes.json` to the price-refresh workflow's `git add` list (a CI change). Any
  difference not explained by the momentum substitution is a defect, and is reported as FAIL.
- **Negative control:** a replay with one input deliberately altered (one ticker's `fundamentals_history` revenue
  doubled) must not match.

## Budget

At most 2 approaches.
