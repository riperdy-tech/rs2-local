# Cross-check L3/L4: point-in-time and replay gates for the factor stage (2026-10-29)

You are asked, as an outside reviewer, to check gate verdicts that Claude reached overnight. Claude both executed and
audited the work. Your reply is advice: Claude rules on each point and records the ruling. You have file access to
`C:\Users\riper\stocks`. Read the files named here; do not rely on this summary alone.

## What was decided

| Gate | Verdict | Evidence |
|---|---|---|
| L-ARCH | PASS | `scratch/rev23/gh_witness_archive/`: 933 runs listed; 648 with logs saved (2026-07-30 to 2026-10-28); 284 expired; 1 not completed. Checksums in `SHA256SUMS.txt`. |
| L-P2/P3 | PASS, paper scope | `scratch/rev23/m3l_verifier/`: run 40608600897 gives 160/160 `PIT_PROSPECTIVE`. The momentum leg is `PIT_VALID_UNPRESERVED`; EPS is present for 9 names and absent for 151. |
| L-P4F | PASS for data-fetch runs; BLOCKED_OWNER for price-refresh runs | `scratch/rev23/m3l_replay/out/`. See the records listed below. |
| L-P1 | PENDING | `scratch/rev23/m3l_pair/out/census.csv` |

Records: `orchestration/RR_L1.md`, `RR_L3.md`, `RR_L4.md` (with its addendum), `RR_L5`/`WO_L5.md`, `RR_L6.md`,
`RR_L7.md`, `AUDIT_L1_L3_L4.md`. The rules are in PLAN Section W.4 (the witness definition).

## Questions (answer each in one or two lines)

1. **The witness rule.**
   - The claim: a scoring run's inputs existed before its witnessed decision time. Its support is that the run checked
     out `head_sha`, recorded by GitHub at run creation, or that another job of the same run pushed the base.
   - **Is there any path by which a scorer input could carry information from after the decision time?**
   - Consider in particular the in-run fetches (stocks.json and prices are fetched during the run itself).
2. **SEC leg.** The SEC leg is bounded by the platform: `fundamentals_history` existed on GitHub before the run, and
   it carries no per-value accession. Is that bound enough for `PIT_PROSPECTIVE`, or does any SEC-derived value reach
   the scorer through a file fetched in the run?
3. **Replay of 40608600897 (L4, rows B/C).** The replay matched only after restoring the momentum values that the
   output itself records. Claude calls that a diagnosis, not a reproduction, and sets the gate to BLOCKED_OWNER for
   price-refresh runs. Agree?
4. **Replay of 36741386328.** The run's momentum was preserved, and the replay is exact from preserved inputs. The
   remaining differences are last-digit `math.log` values and one dict-key position that follows the hash seed.
   **Is anything else needed before calling the factor stage deterministic?**
5. **Negative controls.** The first control, doubling AAUC's revenue, changed nothing. It was replaced by removing
   AAUC's record. Is the replacement control adequate? Should a control on the momentum input be added?
6. **The forward A0 ledger.** It starts at 2026-09-30 because the dual-door engine went live on 09-22. The 09-30 book
   held 9 debentures and preferreds, a since-fixed screener defect, and they are kept in the record. **Keep them, or
   should a corrected series be registered alongside?**
7. **What would you most expect to be wrong** in these verdicts?
