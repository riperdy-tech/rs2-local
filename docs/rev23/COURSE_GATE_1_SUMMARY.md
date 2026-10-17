# Course gate 1: the end of the revision 25 Stage 0.3–0.8 build (2026-10-16 23:50)

**For the course check** (`briefs/BRIEF_COURSE_CHECK.md`). The full record is `../PHASE_4_AMENDMENTS.md`, from "Revision 25 Stage 0.1"
onward. Read it by section, not whole.

## Since the plan v3 additions (22:10)
| Stage | What | Where |
|---|---|---|
| 0.1 | H3 decomposition of the 22 pilot values (done before v3) | `H3_DECOMPOSITION_REPORT.md` |
| 0.2 | the bridge spec v1; v1.1 audit rulings; v1.2 classification checks K1–K4 | `SPEC_rev25_normalization_bridge.md` |
| 0.3 | the bridge desk (desk schema 25.1) | rs2 branch `review-2026-10/rev25-bridge` |
| 0.4 | synthetic set (150 cases); calibration protocol; pilot labels; tolerances frozen; held-out validation | `scratch/rev23/r25_synth/` |
| 0.5 | the classification checks K1–K4 | rs2, merged |
| 0.6 | the two-pass protocol, arms r25_b and r25_c, with consensus withheld in C's pass 1 (pack and desk) | rs2, merged |
| 0.7 | the memo merge after a crux follow-up, r25 arms only | rs2, merged |
| 0.8–0.10 | masking (0 residuals on 22 memos); crux candidates against finals; version stamps | `scratch/rev23/pilot_r25/` |
| Stage 2 | 3 names sealed by a deterministic hash rule; their file hash only is recorded | `scratch/rev23/stage2_sealed/` |

- **The rs2 head** is `9ed16fc`. The full suite has 3,378 passed, with the same 42 known failures by name as `2b799bd`. **Not pushed.**
- **The order the curve-fitting check needs** (times from `PHASE_4_AMENDMENTS`):
  1. definitions;
  2. the synthetic README;
  3. the calibration protocol;
  4. the labels;
  5. the gaps;
  6. the freeze.

  Each was hashed before the next.
- **The values:** τ_m 0.03, τ_R 0.10 and τ_b 0.01, all from priors. They equal the 0.3 placeholders, which came from the same prior, and the
  record says so. **τ_g 0.02** is a prior.

## Remaining before Muse's paper book can start
1. **Cross-check 21:** an outside AI review of the decomposition, the spec, the frozen thresholds and the Stage 1 registration, with the
   replies ruled.
2. **The Stage 1 runner:**
   - stage P for the r25 arms, including freezing `_withheld_consensus.md`;
   - stage R with version stamps;
   - the Stage 1 registration: 8 names × arms A, B and C, plus repeats, 28 runs.
3. **Stage 1 GPU runs:** about 5–6 hours. Then the blind scoring, then the arm selection by the pre-registered rule.
4. **If Stage 1 passes:** the paper-only Muse book starts (plan v3).
- **The expected start date of the paper book:** about 2026-10-20 if cross-check 21 returns within a day. This is the first gate, so
  there is no earlier date to compare against.

## Known open items
- **Pushing:** the rs2 branches `rev24-muse` (after `e8b8a9b`) and `rev25-bridge` are not pushed. The secret scan comes first.
- **The nightly baseline:** nights 2 and 3 still need the AK.89 check and publication by hand.
- **The Stage 2 pool** comes from the 2026-09-16 screener nomination list, the newest in `stock-screener/public/data`.
