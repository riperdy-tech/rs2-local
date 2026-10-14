# Brief G2B: the gate-2b v3 census pipeline (SPEC_rebuild AK.53, AK.57, AK.58, AK.60)

## Where and how
- **Repository:** `C:\Users\riper\stocks\rs2-local`. Create the worktree `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-g2b-census`
  on a **new branch `review-2026-10/gate2b-census` from commit `c210785`**. Work only there.
- **First commit:** apply `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\patch_ak58_item701.patch` unchanged (`git apply`), run
  `rebuild_harness/gate2/tests`, and commit it as "AK.58 (b): SEC 8-K Item 7.01 counts as public (coordinator's patch)".
- **Your limits:**
  - Never touch any other checkout or worktree. In particular, never touch `wt-gate2-dev`, where another session's run records `code_dirty`,
    or `wt-g2b-prep`, which the coordinator's 07-31 preparation uses.
  - Never push, merge or deploy.
  - Commit by pathspec, with messages ending `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest valuation rebuild_harness -q`. Record the counts before and after.
- **Memory:** the PC has about 12 GB and is often near full. Before any run heavier than a unit test, wait until
  `(Get-CimInstance Win32_OperatingSystem).FreePhysicalMemory` is above 2.5 GB.

## Two prohibitions, absolute
1. **Never run anything on 2026-07-31** (or 08-31, 09-30, 10-30):
   - no valuation;
   - no outcome extraction;
   - no reading of any file under `data/gate2b_0731` except `ctx/universe_2026-07-31.json`, and that only once the coordinator says it
     exists.

   The coordinator runs every 07-31 step after the freeze.
2. **Rehearse only on gate 2's 2026-06-30 state**, through scratch copies (the `e8_gate2b.prepare_scratch` recipe), and score rehearsals
   only on **dummy outcomes** that you generate. Never write into `data/gate2_run2` or `data/gate2b_0731`.

## Read first
- `C:\Users\riper\stocks\AGENTS.md` and the repository's `AGENTS.md`.
- `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\rev23\REGISTRATION_gate2b.md`: the whole v3 section (items 1–12), and
  sections 1–4 with the AK.37 v2 amendment. **Where v3 says otherwise, v3 governs.**
- The existing code to reuse rather than copy:
  - `rebuild_harness/gate2/`: `env.py` (`RealEnv.company_inputs`), `sample.py` (write-once, sha256), `baselines.py` (the runrate PERSIST
    and POPMED of Addendum AH), `outcome_extract.py`, `eligible_outcomes.py`, `same_filing.py`, `scoring.py` (`paired_errors`, `_quant`,
    `cluster_bootstrap_median`, the G1 rule);
  - `rebuild_harness/forensics/e8_gate2b.py` (v1 and v2 on the same inputs), `e5_v2.py` (lineage), `e8_score.py` (`rows_of`).

## What to build, in `rebuild_harness/gate2b/`
1. **`config.py`.** The registered constants, in one place:
   - the date 2026-07-31; the state folder `data/gate2b_0731`;
   - 2,000 draws, seed 20261013; the minimum samples (200 per operating measure, 100 for the ROTE change);
   - `PUBLIC_ITEMS` ("2.02", "7.01").

   The engine version, the near-term tables folder and the priors folder are **parameters read from a freeze file**, never written in
   code: the engine freeze is being finished by another session.
2. **`census.py`: universe and sample.**
   - **The source:** `ctx/universe_<date>.json` (written by `env.prepare_dates`).
   - **The filters, in this order,** each counted, with every excluded company listed with its reason:
     1. commodity out of scope;
     2. a 10-Q accepted in the 12 months before T (from the point-in-time submissions; foreign 20-F/6-K filers fail this);
     3. not in gate 2's 2026-06-30 sample (`data/gate2_run2/sample/sample.json`, its hash verified);
     4. engine v2 values it at T (the CPU pre-check with information at T only; refusal reasons are recorded).
   - **The sample file:** written once, in gate 2's sample format, with its sha256 beside it.
   - **A flag on each company:** `in_any_gate2_date`, for sensitivity (e) of item 12.
   - **The attrition table** of item 12 (c): the universe; the gate-2 overlap; public at T; the 120-day guard; the scored sample. The last
     three counts are filled in at scoring.
3. **`value.py`: the CPU valuation.** Adapt `e8_gate2b.py` to any date's state folder and sample.
   - **Per company:** CODE = v1 exactly as `valuation.muse.pipeline.run_company`'s code arm (the prior alone); V2 = engine v2 from the
     freeze's tables. Both run on the same inputs from `RealEnv.company_inputs`, with `fetch_documents=False`.
   - **Records:**
     - the fiscal-year-1 P50s of growth, the margin change and the ROTE change for each arm;
     - each refusal with its reason;
     - the base year;
     - the mean-value horizon decomposition of item 12 (g): the share of value from years 1, 2–3 and 4 onward, where the engine exposes
       it (if it does not, say so and list it as a gap; do not change the engine);
     - V2's year-1 P10/P90 (for the reported q1 interval diagnostic, item 12, not adopted as a bar).
   - **The output:** write-once per company, in the shape `e8_score.rows_of` reads, with a lineage file (code commit, `code_dirty`, table
     and priors hashes, the sample hash).
   - **Report** the per-company time on the rehearsal.
4. **Baselines.** Run `gate2.baselines` on the census state with no change, if it can. If it cannot, say why before changing anything.
5. **`outcomes.py`.** `gate2.eligible_outcomes` with `PUBLIC_ITEMS`, over the census sample; the register and the exclusion counts.
   - **Report the extra exclusions due to Item 7.01 alone** (public through 7.01 and not through 2.02 or the pack).
   - The scoring date is a parameter.
6. **`score.py`: the bars of v3 item 5, with item 12 (a)'s inference.**
   - **Arms:** SYSTEM = V2; CODE; PERSIST (`runrate`); POPMED (`pop_median_runrate`).
   - **Measures:** growth and the margin change (operating); the ROTE change (financial). Forecasts and outcomes are paired as G1 pairs
     them: the annual forecast against q1, with the shared mismatch.
   - **The statistic:** per bar, the paired median of d = |A − y| − |B − y| over companies where both arms and the outcome exist. A beats
     B when the median is < 0 and the upper end of the one-sided 90% bootstrap interval (the 0.90 quantile of the bootstrap medians, as in
     `gate2.scoring`) is < 0.
   - **The primary interval:** a cluster bootstrap by SIC 2-digit industry. Count the companies per industry within that bar's paired
     sample; an industry with fewer than 5 is pooled into one cluster per family (`pool:<family>`). It uses 2,000 draws and seed 20261013
     for every bar.
   - **Beside it:** the company-clustered interval, with the same draws and seed.
   - **The bars:**
     - B2: V2 beats PERSIST and POPMED on growth and on the margin change; V2 beats PERSIST on the ROTE change.
     - B3: V2 beats CODE on all three measures.
     - A bar below its minimum sample reads NOT DECIDED.
     - **The verdict:** PASS only when every B2 and B3 bar passes. Otherwise FAIL (or NOT DECIDED where a bar lacks its sample).
   - **Every bar is also reported on the total-revenue-verified rows only** (AK.37 v2 item 2).
7. **`diagnostics.py`: the reports of items 11 and 12, none a bar.**
   - **The target quarter:** its end date, its distance from T, and whether it is the late-reported June quarter or a later quarter.
   - **Paired errors** by reporting delay, size decile and family.
   - **Concentration:**
     - the median d with the 10 companies of largest gain (most negative d) removed;
     - the median d with each SIC-2 industry left out in turn.
   - **Selection reconciliation:** the eligible universe against the scored q1 sample, on market cap, family, SIC 2-digit, filing delay,
     leverage, C0 P(fail) and prior growth volatility.
   - **Strata:** B2/B3 within quarter-end month, market-cap tercile and family.
   - **The reweighted score (inverse probability of selection):** cells of SIC 2-digit × size tercile × quarter-end month; the weight is the
     cell's universe count over its sample count; a weighted median of d. A cell with sample count 0 is reported, not imputed.
   - **Sensitivity (e):** every bar recomputed excluding every company that is `in_any_gate2_date`.
   - **The q1 coverage of V2's year-1 P10–P90,** reported with the caveat that it is an annual band.
   - **A hook for the period-authority annotation** of the other session: an optional JSON keyed by cik, carried into the records and
     reported by its values. Its format will be given; leave the hook generic.
8. **One report** (markdown and JSON), negatives first, opening with the item 11 statement of what the test is.

## Tests
- **Synthetic:**
  - a planted advantage is recovered, and no advantage gives a median near 0 and FAIL;
  - the industry pooling rule (fewer than 5 pooled per family);
  - the cluster bootstrap on a toy case checked by hand;
  - NOT DECIDED below the minimum;
  - the attrition counts add up;
  - the reweighting on a toy case.
- **Rehearsal, end to end, on gate 2's 2026-06-30 state** (scratch copies, at most 40 companies, dummy outcomes): census, then valuation,
  then baselines, then dummy outcomes, then scoring, then diagnostics.
- **The suite green** against the baseline counts.

## Deliverable
The branch with its commits, and `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\g2b_REPORT.md` holding:
- the changes;
- the test counts before and after;
- the rehearsal output and the per-company time;
- every judgement call or gap.

Decide nothing the registration leaves open; list it. The coordinator writes the independent recomputation separately and audits every
line before anything runs on 07-31.

## Amendment AK.62 (2026-10-14 22:07): the requests of the engine-v2 session (fork 2), adopted
1. **Value V2 through the engine's own `run()`,** with a real `PopulationPriors(PRIORS_DIR)`, not through `e5_v2._Fixed` or
   `gate1.PreBuiltPriors`. Engine v2.1 reads its measured continuation from the priors' tables (`near_term.continuation(priors, ps,
   family)`), and those wrappers have no `.tables`, so v2.1 would fall back to K without saying so. On v2.0.3 the call changes nothing.
2. **Record on every row:**
   - `engine_version`;
   - `continuation` (v2.1's source string, or "K: ..."; absent on v2.0.x);
   - `base_accession` and `base_period`.
3. **The period-authority hook (item 7):** fork 2 produces the annotation from `sample.json` plus each row's `base_accession`. It joins on
   (cik, base_accession), and it **annotates, never drops** (AL.39).
4. **Never hard-code** `near_term.CHAIN_VERSION` checks: v2.1 reports "v2.1". The version is read from the freeze.
5. **Drop `e8_gate2b`'s run-2 copy and fingerprint aborts** for the census, since no run-2 context exists for 07-31. Pin a freeze manifest of
   your own instead: the code commit, `code_dirty`, the priors and tables sha256, and the sample hash, as `e5_v2.lineage()` does. On the
   06-30 rehearsal the run-2 copy recipe stays, because it is the rehearsal's input.
