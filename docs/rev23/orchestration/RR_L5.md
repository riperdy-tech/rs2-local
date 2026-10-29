# RR_L5: Publication pair (stocks.json / reverse_scores.json), paper scope

**Result:** DONE. Gate **L-P1: PASS for paper scope** on the first post-fix output, with the residual items listed
below.

## Census (`stocks-workspace/scratch/rev23/m3l_pair/out/census.csv`)

- **Method:** the owner's `check_paired_publication.validate` (at `3094fc70`, unmodified), applied to the git blobs of
  every `main` first-parent commit since 2026-08-26 that touched either file. 168 commits.
- **Every price-refresh output passes** (30 of 30).
- **Every data-fetch output fails** (104 of 104), as do 24 of the 26 merge commits. In each failure about 6,550–6,570
  stocks lack the embedded Reverse record, and up to 96 are unequal.
- **Negative control:** the method reproduces the known historical failures, for example `13f3796e` with 6,564
  missing and 94 unequal, which the register cites.
- **Cause:** the old data-fetch workflow committed `stocks.json` in its fetch job, and its score job committed
  `reverse_scores.json` without the re-embedded `stocks.json`. The pair was therefore inconsistent from each daily
  data fetch until the next price refresh, every day since 2026-08-27.

## First output after the fix

- **Run:** 40707381769, Scheduled Data Fetch, `workflow_dispatch`, on `rs2-pc`, 2026-10-28 14:35–16:27Z. It ran the
  new single-job atomic workflow.
- **Output commit:** `e41974be`, "Auto-update: Atomic fetch + score publication", parent `3094fc70`.
- **`validate`:** 7,012 / 7,012 exact pairs. **PASS.**
- **The guard ran twice** (GitHub log): `PASS paired publication: 7012 exact stock/Reverse records`, once at 16:26:56Z
  before the commit and once at 16:27:02Z after the merge. The push was `3094fc7083..e41974be3b` at 16:27:19Z.
- **The same run passes the WO_L3 verifier v1.2** (163 `PIT_PROSPECTIVE`; MRI: live peer copied and committed).
- **Its factor stage replays exactly** from committed inputs (`m3l_replay/out/FINAL_40707381769_atomic.json`). That
  needed the runner's local date: 2026-10-29 KST.

## Residuals (annotations; they do not block paper scope)

- **The price-refresh workflow** also gained the guard in `3094`. Its first post-fix run is the 21:05Z cron on
  2026-10-28. Cron delivery drifts: the last runs started at about 00:25Z, which is about 09:25 KST. That run is to be
  checked the same way.
- **Served HTTP parity** (the Vercel-protected copy): `UI_SERVED_PARITY_UNVERIFIED` unless the operator supplies the
  two served bodies.
- A second data-fetch run (40724004456) was still `in_progress` at archive time. It is now checked; see the addendum.

## Addendum, 2026-10-29 03:10 KST: second post-fix output

- **Run:** 40724004456 (Scheduled Data Fetch, cron, **GitHub-hosted**).
- **Output:** `ed661784`, which passes 7,012 / 7,012. The verifier passes it (163 `PIT_PROSPECTIVE`, momentum
  preserved).
- **Pushed tip:** the merge `fcf8594` (parents `ed661784` and `e41974be`), which also passes 7,012 / 7,012.
- **So both runner types pass after the fix.** The routine check is now one command:
  `m3l_verifier/check_new_runs.py --since <utc>`.

## Addendum, 2026-10-29 10:20 KST: first post-fix price refresh

Run 40796224964, output `92592e21`: 7,012 / 7,012 pairs, and the verifier passes it. **All three post-fix output kinds
pass:** PC data fetch, GitHub-hosted data fetch and price refresh.
