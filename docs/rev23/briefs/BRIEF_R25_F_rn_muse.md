# Brief F: the `rn_muse` paper book (built now, activated only if Stage 1 passes)

**The goal:** when Stage 1 passes, Muse's revision-25 verdicts trade a **paper-only** book at once, graded by TRK-06 like the others.
**Nothing is activated, published or deployed by you.**

## The safety rule (real money)
- **The KIS real-money mirror copies `rn_depth`.** `rn_muse` must never write `depth_overlay.json`, never enter `rn_depth`, and must sit
  in `scripts/kis/targets.py` `PAPER_ONLY_LEDGERS`.
- **A test asserts** that `targets.py` refuses `rn_muse` weight, as `scripts/test_rn_gemini_ledger.py` does for `rn_gemini`.

## Model it on `rn_gemini`
**On the screener's `origin/main`:**
- `scripts/track_paper_portfolios.py`;
- `scripts/kis/targets.py`;
- `scripts/test_rn_gemini_ledger.py`;
- `lib/data-service.ts`;
- `components/desk/track/PaperBooks.tsx`;
- `public/data/paper_ledgers.json`.

**Its overlay builder:** `stocks-workspace/baselines/gemini/build_gemini_overlay.py`.

## Workspaces
- **Screener:** create your own worktree. **Never use the shared `stock-screener` tree:** another session's branch is checked out there.
  `git -C C:/Users/riper/stocks/stock-screener worktree add -b feat/rn-muse ../stocks-workspace/scratch/rev23/wt-screener-muse origin/main`.
  Commit there by pathspec. Never push, never touch `screener-publish`, never deploy.
- **The overlay builder and the producer:** `stocks-workspace/baselines/muse/`, new, with no git.

## Build
1. **`build_muse_overlay.py`.**
   - It reads Muse verdict rows (`verdict_depth.json`) from one input folder of finished paper runs. The folder layout is the Stage 1
     runner's: `runs/<T>/<arm>_s<S>/<T>_<ts>/`.
   - It keeps only runs whose `desk_schema` is 25.1 and whose arm is the one named on the command line.
   - It writes `muse_overlay.json` (scheme `muse_paper_v1`) with the same shape as `gemini_overlay.json`. Per name:
     - the verdict label, the values, the date;
     - the `desk_schema`, the arm and the version stamps;
     - `bridge_checks` and `class_checks` with any unresolved fails;
     - the run's failure class, if any.
   - A run that is not usable (a v4 failure class or `two_pass_breach`) is carried with that status and **never selected**.
2. **The `rn_muse` ledger** in `track_paper_portfolios.py`.
   - Use `rn_gemini`'s selection rule unless it does not fit Muse's labels. Say which, and why.
   - **Before you finish,** run the rule on a fixture of the 22 pilot verdict rows (`scratch/rev23/pilot_r24/runs/*/*/*/verdict_depth.json`,
     relabelled as if 25.1) and **report what it selects, by sector and by label.** The `rn_v4` launch showed a rule must be checked for
     what it actually picks before anyone approves it.
3. **`PAPER_ONLY_LEDGERS` and the UI.** `rn_muse` is added to `PAPER_ONLY_LEDGERS`, `paper_ledgers.json`, `data-service.ts` and the
   PaperBooks track column, mirroring `rn_gemini`. The stock-page panel is optional: do it only if it is a small mirror of GeminiPanel.
4. **The TRK-06 entry.** Find how `rn_gemini` and `rn_v4` are registered for TRK-06 grading (30/60/91/182/365 days) and register
   `rn_muse` the same way.
5. **The producer, a stub only:** `baselines/muse/README.md` describes how a paper night would run, and nothing more. It runs
   `depth_pipeline` on the book's names under the chosen arm, writes to a dedicated folder, then builds the overlay. It is written up
   for the coordinator's review only; nothing is scheduled.

## Tests
- `test_rn_muse_ledger.py`, mirroring `test_rn_gemini_ledger`: the paper-only refusal in `targets.py`, and the ledger built from a fixture
  overlay.
- The overlay builder: the arm and schema filter; not-usable runs are never selected; a fixed fixture gives the expected file.
- **Run the screener's Python tests** that touch `track_paper_portfolios` and `kis/targets`. Report any failure, and whether it also
  fails on `origin/main`.

## Report
- the commits and files;
- the selection rule and its preview (counts by sector and label);
- the test counts;
- what activation needs (for the coordinator);
- ambiguities.
