# CLOSE 3M: 2026-10-29

**Decision: PASS.** Qwen is the required analysis engine through `qwen_c`.

- **What qwen_c is:** a frozen, replayable primary-source packet; seven separated tasks through our own template and parser; and a versioned output contract that checks every figure and quote.
- **Its authority:** none. Its output is not yet scored against ground truth; that is 3N.
- **Who closed it:** Claude, under the operator's standing go of 2026-10-29.

## Gates

| Gate | Verdict | Record |
|---|---|---|
| M-P4 pack replay (moved from 3L) | **PASS**: 5/5 real packets (T 2026-10-29T02:28:48Z, screener `92592e21`, verifier PASS / pair PASS) replay byte-identical offline; negative tests pass | AUDIT_M2, WO_M4 |
| M-CONTRACT | **PASS**: 268 tests, including the reviewer's false-support probes and the statement rule | AUDIT_M3, CROSS_CHECK_M_RULINGS, RR_M-LIVE |
| M-ERR | **PASS** (stub server): malformed, timeout, 500, overflow, crash, prior_unusable | RR_M3, RR_M4B |
| M-REC | **PASS**: unit tests; on the 7 real runs, 105 sha256 plus 49 turn files recompute, 0 mismatches | RR_M-LIVE |
| Cross-check before the GPU | **DONE**: Gemini, 30 points: 24 FIX, 6 NOTE | CROSS_CHECK_M, CROSS_CHECK_M_RULINGS |
| M-LIVE | **PASS**: MA smoke, then CMRE, HRTG, ILMN, ECPG and MA twice. 7/7 `complete`, 42/42 tasks ok on the first attempt. 276/399 claims supported under the final contract | AUDIT_M5, RR_M-LIVE |

**PLAN §3M work items:**
- **1–8** are covered by SPEC_m3m_qwen_pipeline.md with Amendments 1 and 2.
- **9** holds: qwen_c contains no valuation machinery, and Revision 26 stays frozen.

## Code

rs2-local branch `review-2026-10/m3m-qwen`, pushed 2026-10-29 after a secret scan. It is based on `r26-harness` 481d0cf and adds only `qwen_c/`.

| Commit | Change |
|---|---|
| 42640f8 | the initial build |
| f584410 | the year exemption |
| 70e3eee | the cross-check rulings |
| 2e12d37 | the smoke fixes and prompt v2 |
| e7c9f72 | the statement rule and the dates |
| bac4cf8 | the year lists and ranges |

**It is not merged into any live branch.** Nothing schedules it, and it writes nothing to rs2-state, the overlay or the screener.

## Holds, unchanged

- `KIS_HALT`
- `DEPTH_PAUSED`
- `model_release_blocked=true`

## Carried into 3N

1. **Run-to-run spread.** Identical MA runs differ by about 8 points in support rate. Cited-figure overlap ranges from 0.35 (competitive_position) to 1.00. Any accuracy figure must carry this spread.
2. *(withdrawn: R-file member labels are kept as header lines; see RR_M-LIVE finding 1.)*
3. **The ILMN cross-reference 10-K layout** leaves its sections NOT IN PACKET. A census of that layout is needed.
4. **`num_predict` headroom:** the largest reply used 11,232 of 12,288 tokens.
5. **Known contract false negatives:** a prose table's "(in millions)" scale, a year with no year word, and enumeration markers.
6. **`supported` certifies presence, not meaning.** Sign, period and attribution are 3N's measurement.
7. **Still open from the earlier milestones:**
   - foreign 6-K/40-F exhibits;
   - the HRTG amendment title wording;
   - the 2031 calendar bound;
   - screener placeholder zero prices.

## Carried checks from 3L

- **C2:** rerun `forward_ledger.py` after the 2026-11-02 fill.
- **C3:** the f99cdda5 change request (keep the years and annotate them).

Neither blocks 3N.
