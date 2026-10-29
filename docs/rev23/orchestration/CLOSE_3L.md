# CLOSE 3L: 2026-10-29

**Decision: `PASS_PROSPECTIVE` for the factor stage, paper scope.** Closed by Claude under the operator's standing go
of 2026-10-29 ("no more approval needed for pushing, and for milestones, do NOT wait"). This replaces the signoff step
in PLAN W.2 step 6 and §3. `CLOSE_3L_DRAFT.md` is kept as the record of the draft.

This certifies nothing historical and nothing about Qwen. Under PLAN §3L the Qwen pack replay is a 3M gate.

## Gates

| Gate | Verdict | Record |
|---|---|---|
| L-ARCH witness preservation | **PASS**: 936 runs listed, 648+ with logs, back to 2026-07-30 | RR_L1, AUDIT_L1_L3_L4 |
| L-INV code inventory | **DONE**: the rs2 live branch was restored to `e82a08b`; ChatGPT's 7 commits are kept on `review-2026-10/m3l-rs2-custody` | RR_L2, RR_L2_partial |
| L-P2/P3 per-candidate PIT table | **PASS** (paper): 160/160 for run 40608600897; 79/79 dual-door runs | RR_L3 (+ addendum) |
| L-P4F deterministic replay | **PASS for data-fetch runs** (three exact replays). Price-refresh runs: the owner fix is now on `main` (below); **carried to 3M as check C1** | RR_L4 (+ 2 addenda) |
| L-P1 publication pair | **PASS (paper scope)**: both post-fix outputs 7,012/7,012 on both runner types. Served HTTP copy unverified | RR_L5 (+ addendum) |
| L-FIX small fixes | **DONE and pushed** | RR_L6 |
| L-H historical | **CLOSED_UNVERIFIABLE** for forensic reads; Gate-2 FAIL, 0/163 and 0/29 unchanged | register §L-H |
| Forward record | **STARTED**: A0 formation 2026-09-30 (60 names), OPEN | RR_L7 |
| L-P5 signoff | **this file** | |

## Commits pushed

`stock-screener` `main`, fast-forward `fcf8594d..77adae57`, 2026-10-29 ~00:45Z. The four `3l-fixes` commits were rebased
onto `fcf8594d`; their code is byte-identical to the audited `e0f8d768` tree (`git diff e0f8d768 HEAD -- scripts
.github` is empty). Suite: 707 passed, 3 skipped.

- `e173ebca` mri_sync read-once
- `7fc17385` fetch_eps_trajectory failure cache
- `5d0d4496` price-refresh.yml commits `daily_closes.json` and `momentum_state.json` (CI change; the label "needs
  operator approval" was dropped from the message, because the push was the pending approval)
- `77adae57` tradability.scan uses the UTC date

## Verified on real data, and not

- **Verified:** GitHub-held witnesses for 79 dual-door runs; three exact factor-stage replays from committed inputs;
  the pair on two post-fix outputs and one merge.
- **Not verified:** the served HTTP pair (it needs a Vercel-authenticated fetch); the historical forensic reads
  (closed as unverifiable); price-refresh replay (C1).

## Carried checks (3M runs these; none blocks 3M)

- **C1.** The first price-refresh run after `77adae57`: run `check_new_runs.py`, and replay it with
  `replay_factor_stage.py` without `--momentum-from-output`. Expect an exact replay.
- **C2.** Rerun `forward_ledger.py` after the 2026-11-02 fill, to close the October A0 period.
- **C3.** The WO_L8 change request (keep years, annotate guarded cells) before any merge of `f99cdda5`.

## Prerequisites for 3M

These hold:
- Factor-stage outputs are `PIT_PROSPECTIVE` under the verifier, and the verifier is the input check for the 3M pack
  replay.
- Holds unchanged: `KIS_HALT`, `DEPTH_PAUSED`, `model_release_blocked=true`. SENEA, SENEB, MOV and MG stay excluded.

## Operator decisions

None blocking. Two options are open: a weekly scheduled archive/ledger task, and the served HTTP check.

## Carried check results

- **C1 DONE (2026-10-29):** price-refresh run 40796224964 replays exactly at the 1e-12 rule, with momentum committed and
  `PIT_VALID`, and its pair is 7,012/7,012. L-P4F PASS for both workflows. See the RR_L4 addendum.
