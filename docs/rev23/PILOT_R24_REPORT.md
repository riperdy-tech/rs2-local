# Revision-24 Muse pilot: report (2026-10-16)

Registered in `REGISTRATION_rev24_pilot.md` (amendments 1–5, deviations 1–2). The blind scores were hashed before unmasking (sha256
`6158b7e5…`, `PHASE_4_AMENDMENTS.md`). This report reads the four measures separately, as registered. Value-to-price figures appear
only in the informational section.

## The verdict under the registered reading rule
**Expansion is not recommended.**
- The rule requires no incoherent memo in (c). **8 of the 16 iii memos are incoherent.**
- (d) and (a) do not fail. No unsupported outlier was accepted, every directional call had a verified crux, and no systematic copying was
  found.
- The failure is in what the analyst does with its own long-run judgment. The next step is the operator's.

## (c) Cash-flow plausibility, blind
| Arm | Coherent | Questionable | Incoherent |
|---|---|---|---|
| iii_p50 (8 memos) | 1 | 1 | **6** |
| iii_no_p50 (8 memos) | 2 | 4 | **2** |
| **By name** | CMRE 3 of 3 | AMD 2, MPWR 2, LAMR 1 | MU 4 of 4, AMD 2, MPWR 1, UGI 1 |

**Two systematic failures.**
1. **The analyst states a normalized earnings figure, then enters a path that does not reach it.**
   - In 9 of 16 memos, the desk's year-10 earnings are 1.8× to 4.7× the analyst's own stated "normalized mid-cycle earnings".
   - Example: on AMD the memo says normalized earnings of $12B, while the inputs it passed produce $45–54B by year 10.
   - The briefing asks for near-term earnings, normalized earnings and the transition, but **nothing connects those statements to the desk
     inputs.** The analyst writes them as prose and then sets growth separately.
2. **The classifications contradict the path entered.** This happens in 7 of 16 memos:
   - "peak" or "decelerating" while years 1–2 accelerate (AMD +46% → +108%, MPWR +50%/+45%);
   - MU called "mid" at an operating margin of 74.6% against its 8-year median of 24%.

   Years 1–2 almost always follow the consensus levels, even when the analyst's own classification says the cycle has turned.

**What worked:**
- the shipping company (CMRE) memos are coherent in all three runs;
- every classification is a valid value;
- every Section 12 field is present;
- the long-run margins are mostly inside the population ranges, with reasons tied to the company.

## (a) Clustering and presentation
- **At P50:** 1 of 12 chosen inputs in `iii_p50`; 0 in `iii_no_p50`.
- **At a printed quantile:** 0.
- **Outside P10–P90:** 0.
- **Spread across names:** wide. The long-run margin's percentile spans 49–58 points.
- **The constancy test flags `iii_p50`'s growth path,** but only 2 names had a percentile, so that flag is weak.
- **No systematic copying.** The population ranges are not being copied.
- **P50 shown against hidden:**
  - the chosen percentiles differ by 0–12.5 points;
  - `iii_p50` scored worse on (c) (6 incoherent against 2), but with n = 8 a side that is not a reliable difference.

## (b) Stability (second seed)
| Name and arm | Base value spread | Labels |
|---|---|---|
| CMRE iii_no_p50 | 0.8% | agree |
| MU iii_no_p50 | 2.5% | agree |
| MPWR iii_no_p50 | 2.8% | agree |
| MU iii_p50 | 11.9% | **split** (undervalued against hold: the second seed lost its crux, `quote_not_found`) |
| AMD iii_p50 | 16.9% | agree |
| AMD iii_no_p50 | **130%** | agree (both hold; the second seed cut years 3–5 growth by 13–25 points and the fade by 3 years) |

## (d) Evidence
- **Gate:** 16 of 16 passed and nothing was rejected. Almost no input landed outside P5–P95, so the gate did not bind. The only outlier
  citations were "related" or "generic", and the gate did not depend on them.
- **Crux citations:**
  - causal where a filed margin bounds a price-implied margin (5 memos);
  - "related" for every growth, RONIC and fade crux, where a quarter's guidance stands in for years 3–5;
  - 26–30% of crux citations did not resolve;
  - no valid crux on 2 of 8 runs in each arm, which correctly became hold.
- **Directional calls without a crux:** 0.
- **The crux form** (Muse's AT10b weakness): 3 desk refusals named it in `iii_p50` and 0 in `iii_no_p50`. Every directional verdict had a
  verified crux.

## Process and compliance
| Measure | Result |
|---|---|
| Runs | 22, in 3 h 46 min (7–17 min each) |
| Server | one instance, no restarts or server errors; the pins held before and after every run |
| Malformed desk calls | 0 |
| Refused desk calls | 37–44% (mostly the desk asking for a reason before it would value) |
| **Memos lost after the crux follow-up** | **4** (LAMR, MPWR and two MU): the final memo says "unchanged from prior memorandum" and the earlier sections are not in the saved report |

## Informational (no bar is set on these): the final value ÷ price
| Name | rev22 | iii_p50 | iii_no_p50 | Formula reference ÷ price (never shown in iii) |
|---|---|---|---|---|
| AMD | 0.53 | 0.36 / 0.42 | 0.56 / 0.24 | 0.52 |
| MPWR | 0.59 | 0.60 | 0.31 / 0.31 | 0.40 |
| MU | 1.97 | 1.58 / 1.77 | 1.85 / 1.89 | 1.75 |
| CMRE | 2.17 | 1.95 | 2.08 / 2.07 | 2.19 |
| UGI | 1.46 | 1.78 | — | 1.52 |
| LAMR | 0.88 | 0.70 | — | 1.09 |

**Plainly:** without ever being shown the reference, the new briefing's values still sit near it, and the census's skew remains:
- growth names at 0.24–0.6× price;
- the memory cyclical at about 1.8×;
- the shipping lessor at about 2×.

Two things the briefing still gives all arms are years 1–2 at the consensus levels and the same base. Together with failure 1 (the
stated normalization never entered), they likely carry the skew, not the printed reference. That is a hypothesis to test, not a finding.

## Deviations recorded
1. **Two labels seen in the run log** before scoring (UGI and MPWR `iii_p50`).
2. **`mask.py` missed** "Strong Buy", scenario MoS columns, momentum percentages and direction phrases in about half the memos. The (c)
   scores rest on the trajectories and the classifications, and that limitation is stated.

## For the operator's decision
The pilot did its job: it found failures before expansion. They sit in the briefing and the desk interface more than in Muse alone:
1. **The normalization is not connected to the desk.** The analyst's stated near-term and normalized earnings and the transition are prose,
   and the path it enters ignores them.
2. **Years 1–2 default to the consensus levels** even when the analyst classifies a peak.
3. **The memo is lost after a crux follow-up** (a harness defect).

**What the coordinator would do next** (not started, and needing the operator's go and a cross-check first):
- make the stated normalization part of the desk call, checked by code against the trajectory, annotated, never clamped;
- check the classifications against the path entered;
- fix the lost memo;
- test whether the skew comes from the year-1–2 consensus levels;
- then run a fresh registered pilot.
