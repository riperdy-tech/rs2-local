# Brief R24 P1: the Muse pilot runner (Phase 4 revision 24, step 3)

## Where and how
- **Tooling folder:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\pilot_r24\` (new). Scripts, a run file and logs live here.
  It is not in any repository.
- **The rs2 code under test:** branch `review-2026-10/rev24-muse` (worktree `scratch\rev23\wt-rev24`). Step 2b is still being built there.
  **Never edit that worktree.** The pilot runs from a separate detached tree that `make_tree.sh` creates at a commit the coordinator names.
- **Never in this task:**
  - load a model or start llama-server, Ollama runs, research, discovery or any GPU work. You build and test the tooling; the coordinator
    launches;
  - push, merge or deploy; delete files; edit `.env*` or `.secrets.json`;
  - touch production `rs2-local` state (`cache/`, `enrich/`, `research/`, ledgers, `config.json`);
  - write to any ledger other than the pilot tree's own test ledger.
- **Memory:** about 12 GB of RAM. No heavy CPU sweeps.

## Read first
- `docs/review_2026-09-22/REGISTRATION_rev24_pilot.md`: the design you implement. Names, arms, seeds, the run order, the measures.
- `docs/review_2026-09-22/PHASE_4_REV24_MUSE.md` (v2), and `PHASE_4_AMENDMENTS.md` from "Revision 24" on.
- **The production chain the pilot must reproduce, stage for stage** (`rs2-local/depth_pipeline.py` `main()`, read in the branch):
  1. the screener-data provenance;
  2. `enrich_error_gate`;
  3. the live quote (`price_now.quote`);
  4. `run_research` (deep research on Ollama; it frees the analyst first);
  5. `llamacpp_server.ensure_ready`;
  6. discovery (`catalyst_research.run`, on the analyst model; its cached brief is embedded in the pack);
  7. `run_consensus` (`consensus_valuation.py --tools`, with `--price` and `--price-asof`);
  8. `band_verdict`, then `stamp_and_route` with `RS2_RUN_SOURCE=gate_test`.
- `consensus_valuation.py` `main()` (the `--pack-file`, `--evidence-store`, `--samples`, `--no-early-stop`, `--seed-base`, `--out-dir`,
  `--price` and `--price-asof` options; the frozen pack must already carry `RESEARCH_ADDENDUM`).
- `llamacpp_server.py` (`start`, `stop`, `status`, `check-pins`, `begin-run`; it refuses when the card is busy).
- **The AT10b record** in `PHASE_4_AMENDMENTS.md` (search "AT10b tooling", "AT10b set up", "AT10b run and score"): how that run built its
  tree, pinned it, guarded the GPU and refused on another session's server. Its scripts are gone; the record is the specification.

## What to build
**1. `make_tree.sh <commit>`.**
- `git worktree add --detach` of the rs2 repository at `<commit>` into `pilot_r24\tree`.
- **`config.json` in the tree, and only there:**
  - `depth_provider` `llamacpp` and `depth_model` the Muse tag (`llamacpp.model_tag`);
  - `research_venv_python` pinned to rs2-local's existing research venv (a pin, not a copy).

  Nothing else changes. The script prints the diff of `config.json` against the commit.
- **Which data the tree needs to build a pack, and from where:** list every cache and data path that `build_pack`, deep research,
  discovery and the desk read: enrich, the closure and COE anchors, the bill-rate store, company news, the SEC caches, screener data, MRI.
  - For each, decide: **fresh** (fetched into the tree by the stage that normally fetches it), or **resolved** (the peer path through
    `paths.py`, read-only).
  - **Never copy production `rs2-local\cache` wholesale.**
  - Report the table.

**2. The run file `run_r24.txt`**, the pins, filled by a script from their named files, never typed:
- the tree commit;
- the `llamacpp` block's sha256s (model, drafter, server command line, system file) and `check-pins` passing;
- the names, the arms, the seeds and the order, exactly as registered;
- the sha256 of each script.

**3. `prep.sh`: stage P, per name, in the registered order.** No analyst runs.
- **P1:** enrich refresh into the tree (`enrich_ticker`), then the error gate.
- **P2:** one live quote. Price and as-of are frozen into `pilot_r24\frozen\<T>\quote.json`; every arm uses it.
- **P3:** deep research, forced, into the tree's `research\<T>.md`. Its sha256 is frozen.
- **P4:** discovery (needs the server: P4 runs after `llamacpp_server start`, all names together, then the briefs are frozen).
- **P5, the arm packs:** for each arm, build the pack offline in the tree:
  - with the frozen quote;
  - with the arm's `pilot_arm` setting (the interface comes from step 2b; read the branch at the coordinator's commit);
  - then `TASK` and `RESEARCH_ADDENDUM`, exactly as `consensus_valuation.py` assembles them for a fresh `--tools` run.

  Save to `frozen\<T>\<arm>\_pack.md` with the facts sidecar, and record the sha256s.
- **P5 checks:**
  - the three arms of a name have identical facts sidecars (except any field 2b defines as arm-specific; list it);
  - `iii_p50` and `iii_no_p50` differ only in the P50 entries;
  - `rev22` contains no POPULATION RANGES section.

  A failed check stops the name.

**4. `run.sh`: stage R, per run, in the registered order** (22 runs). For each run:
- the pins checked before and after;
- `RS2_RUN_SOURCE=gate_test`, `consensus_valuation.py <T> --tools --samples 1 --no-early-stop --seed-base <S> --pack-file <frozen pack>
  --evidence-store pilot_r24\evidence\<T> --price <p> --price-asof <a> --out-dir pilot_r24\runs\<T>\<arm>_s<S>`;
- then `band_verdict` and the gates, exactly as `depth_pipeline` applies them, written to `runs\...\verdict.json` and the tree's test
  ledger only;
- start, end, minutes, the return code, server restarts, VRAM after load.

**Resumable:** a finished run (verdict written) is skipped on restart; a partial run directory is renamed `*_partial_<ts>`, never deleted.
**Refusals:**
- another session's llama-server, or any Ollama model loaded during stage R;
- a pin mismatch;
- a missing frozen artefact.

**5. GPU guard.** It reuses `llamacpp_server`'s own refusals. The runner never kills a process it did not start. A `DISARM` file in
`pilot_r24` stops it before the next run.

**6. `mask.py` (blinding, registration point c).**
- For each `iii` run's `sample1.md`, write `masked\<id>.md` with the price, every per-share value, the formula reference, ratios to price
  and the label replaced by `[MASKED]`.
- The id is random. The key `masked\key.json` is written separately, and the coordinator does not open it until the scores are hashed.
- **Test:** it on 3 saved revision-22 reports (any `ab_reports/consensus/*/sample1.md`), and report what survived masking (print the residual
  `$` amounts).

**7. `measures.py` (registration points a, b, d and the process measures),** from run directories and `tables.json`:
- **(a):** each chosen long-run input's percentile in the printed cohort distribution, the at-P50, at-quantile and outside-P10–P90 rates,
  per arm;
- **(b):** the repeat spreads;
- **(d):** I1–I8 and the plausibility-gate outcomes, from the run's own records;
- the process measures.

**Test:** it on synthetic run directories with hand-computed expected values.

## Tests and dry run
- Unit tests for `mask.py` and `measures.py`.
- **A dry run of `prep.sh` and `run.sh` against stubs:**
  - no network, no model, no server;
  - the stubs replace `enrich_ticker`, `price_now`, deep research, discovery, `llamacpp_server` and the chat;
  - it shows the order, the resume, every refusal and the frozen-artefact checks.
- **A real offline P5** on one name, using that name's existing production enrich and research copied into a throwaway directory outside the
  tree (never into it): the pack text for all three arms is built and the P5 checks pass. This is possible only once step 2b's `pilot_arm`
  lands; until then, report P5 as built and untested.

## Deliverable
The scripts and their sha256s, the data-source table (item 1), the dry-run log, the test results, the masked samples' residuals, and every
judgement call or gap. Reply as text; decide nothing left open.
