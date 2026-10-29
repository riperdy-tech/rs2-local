# RR_L4: Factor-stage deterministic replay of run 40608600897

**Result:** DONE. The gate outcome is `NOT_REPRODUCIBLE_UNPRESERVED_INPUT`, and that cause is the only one found.

## Changes

- `stocks-workspace/scratch/rev23/m3l_replay/replay_factor_stage.py` and `out/*.json`.
- The working trees are in the session scratchpad.

No repository was changed.

## Method

The replay materializes, from git blobs:

- `scripts/` at `ebcdda43`;
- the `HEAD_TREE` and `PREVIOUS_OUTPUT` inputs at `ebcdda43`;
- the `IN_RUN_COMMITTED` inputs at `9046be40`.

The environment for each replay:

- `MRI_OUTPUTS_DIR` points at a path that does not exist, which reproduces the run's `COMMITTED_SNAPSHOT` branch.
- The clock is frozen at 2026-10-28T00:59:44Z. That covers `score_factors_dual_door.datetime`, and also
  `tradability.date`, because `tradability.scan` calls `date.today()` directly.
- Python 3.12 on Windows. The runner used 3.11.17 on Linux, and the scorer is pure standard library.

Comparison is of parsed JSON, minus `generated_at` and the two machine-path fields (`discount_rate_meta.path` and
`sector_ranking_meta.path`).

## Results

| Replay | dual-door output | `factor_scores.json` |
|---|---|---|
| A. Preserved inputs; `momentum_state` = the `head_sha` copy (built by the 10-27 18:24Z data fetch); seed 0 | 2,421 differences | 41,193 differences |
| Same as A, seed 12345 | same counts | same counts. **No dependence on the hash seed.** |
| B. As A, but the momentum fields the output records (`fct_momentum_state`, 51,738 values) restored into `momentum_state` | **equal** | 23 differences, all `jump_share` in the last binary digit (for example 0.7572754340773731 vs …730) |
| C. As B, compared at a relative tolerance of 1e-12 | **equal** | **equal** |
| D. Negative control: as C, with nominee AAUC's `fundamentals_history` record removed | 762 differences | 9,229 differences (AAUC leaves the book; band counts move) |
| D0. A first, weaker negative control: AAUC's revenue doubled | no change | no change |

D0 was kept as a record. It shows the scorer does not read revenue in any output field for AAUC. It was replaced by D,
a perturbation the code guarantees matters.

## Interpretation

- Every input except the momentum state is preserved, and the scorer is deterministic on them, to the last floating
  digit (platform `libm` aside).
- The published decision cannot be byte-reproduced from preserved inputs alone. The run regenerated
  `momentum_state.json` from `daily_closes.json`, which was itself refetched during the run, and committed neither. The
  `head_sha` copy differs: it was built at 18:24Z on 10-27, before that day's close, with the same `price_asof` label.
- Restoring only the momentum values the output itself records closes the dual-door output exactly. That isolates the
  cause to this single input.
- Replay B/C uses the output's own recorded momentum values, so it is a *diagnosis*, not an independent reproduction.

## Gate L-P4F

`NOT_REPRODUCIBLE_UNPRESERVED_INPUT`. The fix needs the operator, because it is a CI change: add
`public/data/momentum_state.json` and `public/data/daily_closes.json` to the `git add` list in
`.github/workflows/price-refresh.yml`. The data-fetch workflow (`schedule-data-fetch.yml`, its second job) **already
commits both files**, so this is a two-line alignment of `price-refresh.yml` with an existing writer, not a new
design. After that, the next scheduled price refresh can be replayed byte for byte, and the gate can be re-run on it.
Separately, runs of the data-fetch workflow should already be replayable; verifying one needs verifier support for its
two-job shape, where the fetch job pushes first and the chain job checks out that push. That is a follow-up item.

## Secondary findings (annotations, not blockers)

- `tradability.scan` takes "today" from the wall clock (`date.today()`), not from the run's clock. A veto that depends
  on day counts ("absent from the exchange listing for N days") therefore depends on when the scorer runs. It is
  harmless in production, where a run lasts minutes, but it is a reproducibility leak. The fix is to pass the run's
  date in (`scan(stocks, today=...)`).
- The 23 `jump_share` values differ in the last digit between Linux and Windows `math.log`. The tolerance comparison
  accounts for this. No decision field changed.

## Addendum, 2026-10-29: second replay, on a run whose momentum *was* preserved

The verifier's v1.1 handles the data-fetch workflow's two jobs: the scoring push's base must be `head_sha`, or a
commit this run's fetch job pushed. Two new tests cover it (11/11 pass). Run 36741386328 (Scheduled Data Fetch,
2026-09-30) passed v1.1. Its `momentum_state.json` and `daily_closes.json` are committed, so all its inputs are
preserved.

The replay of 36741386328 used the preserved inputs only, with **no** momentum restoration. The clock was frozen at
18:20:42Z, the scorer start time in the log.

| Replay | dual-door output | `factor_scores.json` |
|---|---|---|
| Exact, seed 0 | **equal** (parsed JSON minus time and path) | 36 differences, all `jump_share` in the last digit |
| Tolerance 1e-12, seed 99 | **equal** | **equal** |
| Negative control (AAUC's fundamentals record removed) | 577 differences | 8,451 differences |

**Bytes.** After CRLF normalisation, the only byte difference in the dual-door output is the *position* of one key
(`NO_FUNDAMENTAL_HISTORY`) inside `veto_breakdown`. Insertion order there follows a set iteration that depends on the
hash seed, and GitHub's seed is random. Even `generated_at` matched (18:20:42Z). In `factor_scores.json`, the only
differences are the 36 last-digit values.

**Gate L-P4F, revised verdict:**
- **PASS for data-fetch workflow runs:** demonstrated on 36741386328, a deterministic replay from preserved inputs.
- **BLOCKED_OWNER for price-refresh runs:** they need the `df6b4ecb` CI alignment on branch
  `review-2026-10/3l-fixes`.

## Addendum 2, 2026-10-29: a PC (self-hosted) run, and a timezone finding

- **Run 37325951878** (data fetch on `rs2-pc`, 2026-10-05; the live MRI peer was copied and committed). The replay
  from preserved inputs is **equal on both outputs at a tolerance of 1e-12**, once two things are reproduced:
  1. the MRI files the run committed (the verifier first missed the directory `git add`; fixed in v1.2);
  2. **the runner's local date**.
- **Finding:** `tradability.scan` takes `date.today()` in the **machine's local timezone**. On the PC (KST) the run's
  "today" was 2026-10-06, while the UTC date was 10-05. So "absent from the exchange listing for N days" vetoes count
  one day more on the PC than on a GitHub-hosted runner at the same instant. This is a real, systemic determinism
  defect.
  - It is small: one day in a day-count threshold.
  - The fix is surgical: pass the run's UTC date in, `scan(stocks, today=<run date>)`, at the scorer's call site.
  - It is listed for the next owner change. It is not applied tonight, because it changes production behaviour.
- **Final replays** (`m3l_replay/out/FINAL_*.json`):

  | Run | Result |
  |---|---|
  | 36741386328 (data fetch, GitHub-hosted) | exact |
  | 37325951878 (data fetch, PC) | exact |
  | 40608600897 (price refresh) | 2,421 / 41,170 differences; exact once the momentum values are restored |

## Addendum, 2026-10-29: check C1, the first price refresh after `77adae57`

- **Run:** 40796224964 (Post-Close Price Refresh, GitHub-hosted, head `77adae57`). **Output:** `92592e21`, which commits
  `daily_closes.json` and `momentum_state.json`.
- **Verifier v1.2: PASS.** 160 `PIT_PROSPECTIVE`, and momentum `PIT_VALID` (previously `PIT_VALID_UNPRESERVED` on every
  price-refresh run).
- **Pair:** 7,012 / 7,012.
- **Replay** without `--momentum-from-output`, at `--now 2026-10-29T01:13:12Z` (the output's `generated_at`):
  - byte-exact except for last-ulp float differences: 2 in `factor_scores_dual_door.json` (WLYB `jump_share`, …863
    versus …864) and 23 in `factor_scores.json`;
  - at relative tolerance 1e-12 (the rule set in this RR), **0 differences in both files**.
  - Files: `m3l_replay/out/FINAL_40796224964_momentum_committed{,_tol}.json`.
- **L-P4F is now PASS for price-refresh runs too.** BLOCKED_OWNER is lifted. C1 is done.
