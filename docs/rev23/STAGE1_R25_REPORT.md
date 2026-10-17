# Revision 25 Stage 1: the result (2026-10-17)

- **Registration:** `REGISTRATION_rev25_stage1.md` (sha256 `3687cdbc…`), plan v3–v6.
- **The runs:** 28, from 02:19 to 09:14, on 8 hash-drawn names never used in the design. All stamped alike: rubric `3687cdbc…`, runner
  `r25.1`; A at pack and desk 24, B and C at pack 25 with desk 25.1.
- **The blind scores:** `scratch/rev23/pilot_r25/masked/SCORES_stage1.md`, sha256 `bbd13502…`, hashed before the key was opened.

## Verdict by the registered rules: **Stage 1 does not pass.** Neither B nor C meets the expansion criteria
| Criterion (plan v6) | B (10 runs) | C (10 runs) |
|---|---|---|
| Incoherent, at most 1 | 0 ✓ | 1 ✓ |
| Unresolved contradiction, at most 1 | 0 ✓ | 0 ✓ |
| Unsupported outlier, at most 1 | 1 ✓ | 0 ✓ |
| Two-pass breach or lost memo, at most 1 | 0 ✓ | 1 ✓ |
| Directional verdict on an unverified crux, 0 | 0 ✓ | 0 ✓ |
| Runs failing 2 or more of the above, 0 | 0 ✓ | 0 ✓ |
| Stability: one pair may miss | CWEN agrees; MSGE label differs ✓ | CWEN agrees; MSGE repeat not usable ✓ |
| **Against arm A: within 1 run of 10** | **✗** unresolved citations in 2 runs (A 0); missing contract fields in 3 (A 0); invalid labels in 2 (A 0) | **✗** 4, 4 and 1 |

The arm-selection rule would have chosen **B**: 1 run failing any criterion against C's 2. That choice is now moot.
**By plan v3, the next step is the model test (a lower temperature, then a larger or different model), not a revision 26 interface.**

## What the numbers say
**On the blind reading, coherence did not improve on arm A:**

| Arm | Coherent | Questionable | Incoherent |
|---|---|---|---|
| A | 6 of 8 | 2 | 0 |
| B | 5 of 10 | 5 | 0 |
| C | 4 of 10 | 5 | 1 |

- **The caveat:** B and C must declare more (normalization, horizon, labels in the desk call), so they have more ways to contradict
  themselves. The A-against-B/C comparison was not blind, though B against C was.
- **The most common problem is a classification label that contradicts its own cited evidence:** for example "trough" against a Brent peak,
  "mid" against a post-championship peak, or "accelerating" on a decelerating path. That happened in every arm. It is a model weakness the
  new checks only partly catch; K checks cannot run on an unbridged Base.
- **The machinery works mechanically:**
  - 0 unresolved check failures (every failed C or K check got a reason);
  - the withheld consensus never leaked;
  - no directional call without a verified crux;
  - 1 two-pass breach in 20 two-pass runs.
- **The cost:** refused desk calls rose from 41% of calls (A) to 50% (B) and 58% (C), and runs took longer. C's unresolved candidate
  citations rose to 40%.

## Defects found that are not Muse's (for cross-check 21)
1. **The unbridged path loses fields.** CWEN and LIND have negative base-year earnings, so the bridge cannot apply. The 25.1 contract no
   longer carries the S12 figures or the labels, and my earlier ruling made the labels optional there. Result: missing contract fields in 3
   B runs and 4 C runs. This is a design gap of mine, not the model's, but it is counted, as registered.
2. **The year 5 → 6 cash-flow jump** (in every arm, inherited from revision 24):
   - years 1–5 are owner earnings and years 6 on are earnings less g/RONIC;
   - where owner earnings are far below earnings, the long run is several times the explicit years (EQNR: 6.6×–6.8×, in arm A too). Values
     for capital-heavy companies are inflated by construction;
   - **real-money relevant;** to be fixed before any engine or analyst value is trusted.
3. **The "reason loop" class is over-inclusive.** It fires on arm A runs that have no bridge. Each run's class needs checking by hand before
   it is used as a measure.

## What this does not say
- It does not say revision 25 is worse for real money. It says that, on 8 new names, the new interface did not make Muse's memos more
  coherent than revision 24's, and that it cost compliance.
- The registered rules are applied as written. The compliance unit ("refused desk calls") was not defined in the registration, so it is
  reported but not used.
- **The failure stands on rows that were defined:** missing contract fields, invalid labels, unresolved citations.
