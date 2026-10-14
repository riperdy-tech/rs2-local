# Brief D4: the live runner for engine v2, producing verdict-contract-v4 rows (SPEC_rebuild AK.52, AK.53)

## Where and how
- **Repository:** `C:\Users\riper\stocks\rs2-local`. Create the worktree
  `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-d4-runner` on a **new branch `review-2026-10/d4-live-runner`** from
  `origin/review-2026-10/gate2-run2`.
- **Work only there.**
  - Never touch other checkouts or worktrees.
  - Never push, merge or deploy.
  - Commit by pathspec with messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest valuation rebuild_harness -q` (the suite is about 800; record the counts
  before and after) and your own tests.
- **Read first:**
  - `C:\Users\riper\stocks\AGENTS.md` and the repository's `AGENTS.md`;
  - the contract: `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\rev23\SPEC_verdict_contract_v4.md` (all of it, especially
    section 2a, the survival mixture, and section 2b);
  - `SPEC_rebuild.md` addenda AK.52–AK.53 in the same folder;
  - the existing code it should reuse:
    - `rebuild_harness/gate2/env.py` (`RealEnv.company_inputs`: how a company's state, priors and discount are built at a date);
    - `valuation/engine_operating_v2.py` and `engine_financial_v2.py`;
    - `valuation/live_data.py` (the live refresh and its staleness reasons);
    - `valuation/abstention.py`;
    - the distress layer used in gate 2 (`rebuild_harness/gate2/stage2_layer.py`, C0).

## What to build
**`valuation/live_runner.py`**: for a list of (company, as-of date), produce one verdict-contract-v4 row per company. **The system is engine
v2 alone** (AK.52). Muse is not called; rows carry `muse_used: false`.
1. **Inputs:** reuse the gate-2 input path (as `RealEnv.company_inputs` does). Factor out a shared function rather than copy it, if that
   can be done without changing gate-2 behaviour; its tests must stay green. Data freshness comes from `live_data` and gives
   `stale_inputs` reasons. A refusal maps through `abstention.py`.
2. **Valuation:** engine v2. **The engine version is a parameter:** v2.0.3 is being finished by another session, so the runner reads the
   version and tables from a frozen config and never hard-codes them. Draws as the engine does, with common seeds.
3. **The survival mixture** (contract section 2a): with p = `prob_fail_12m` from the distress model in force (C0 until B5 selects
   another), value 0 with probability p, the going-concern distribution otherwise.
   - quantiles: 0 if q ≤ p, else the going-concern quantile at (q − p)/(1 − p);
   - `mean_iv` = (1 − p) × mean;
   - `prob_value_above_price` = (1 − p) × Pr(V > price).

   Test against an independent reimplementation in the test file.
4. **Every v4 field** (contract sections 1–6):
   - versions complete, including `distress_model`, `engine` and the tables' hashes;
   - the quantiles (survival-adjusted and going-concern), `median_iv`, `base_iv`, `mean_iv`, `median_mos`, `mean_mos`,
     `prob_value_above_price`, `prob_fail_12m`, `tv_share`;
   - `direction`, `m`, `size_hint` with `size_components`;
   - entry timing (two axes, from the SCR-10 trend state; find where the screener exposes it, and if it cannot be read, say so and leave
     a clear TODO, never a guess);
   - the watch items (section 5);
   - abstentions (section 6);
   - `consensus_display` left absent unless a source exists;
   - the flags `value_distribution_model_implied`, `joint_tail_undercoverage` (true for any engine whose copula is v2.0's Gaussian) and
     `distress_model_not_validated`.
5. **A CLI that writes rows to a JSONL** in a given output folder (append-only, write-once per run id). No ledger or overlay writes yet.
   The coordinator connects them after review.
6. **Tests:**
   - the mixture formulas;
   - the direction, band and MoS consistency;
   - an abstention is never actionable;
   - every v4 field present, or absent by rule;
   - the version stamps;
   - a real-data smoke on 5 companies at 2026-06-30, through the gate-2 store and context, writing to a scratch folder and never to
     `data/gate2_run2`.

## Deliverable
The branch with its commits, and a report file
`C:\Users\riper\stocks\stocks-workspace\scratch\rev23\d4_REPORT.md` holding:
- the changes;
- the test counts before and after;
- the smoke output;
- every judgement call or gap.

Decide nothing the contract leaves open; list it.
