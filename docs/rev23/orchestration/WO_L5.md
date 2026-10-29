# WO_L5: Publication pair (stocks.json / reverse_scores.json), paper scope

- **Milestone and gate:** 3L, gate L-P1.
- **Executor:** Claude.
- **Issued:** 2026-10-29.

## Goal

Measure stock/Reverse pair consistency on the git blobs that consumers read. Do it for every `main` commit since the
`screener-publish` history begins (2026-08-26) that changed either file, and in particular for the first scheduled-run
output after the `3094fc70` atomic-pair fix. Separately, confirm from that run's GitHub log that the new guard ran.

## Method

- Apply the owner's own validator, `scripts/check_paired_publication.py::validate` at `3094fc70`, unmodified, to the
  `stocks.json` and `reverse_scores.json` blobs of each commit.
- Do it read-only, through `git show`, in `screener-publish`.
- Census output: commit, author, time, PASS/FAIL, and the first failure reason.
- **Post-fix check:** for the first price-refresh or data-fetch run created after `3094fc70`, the verifier's push-line
  logic identifies the output commit. The log must contain `PASS paired publication: N exact stock/Reverse records`
  before the push, and the output blobs must pass `validate`.

## Scope

- **Create only** `stocks-workspace/scratch/rev23/m3l_pair/`.
- **No repository change.** No network beyond `gh` reads of run metadata and logs.

## Acceptance

- The census reproduces the known historical failure on `d6fbdd16` (the register's 6,564 missing / 94–95 unequal), so
  the method can detect a failure. This is the negative control.
- The census shows `9046be40` passing (7,011 pairs).
- **Gate L-P1 (paper scope):**
  - **PASS** when the first post-fix scheduled output passes, and its log shows the guard ran.
  - **PENDING** until such a run exists.
  - **FAIL** if any post-fix output fails.
  - Served-HTTP parity stays `UI_SERVED_PARITY_UNVERIFIED` unless the operator supplies the two served bodies.
