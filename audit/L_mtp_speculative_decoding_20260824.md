# L — MTP SPECULATIVE DECODING ON THE DEPTH TIER (2026-08-24)

**Result: +66% throughput against the incumbent, quality unchanged (4/4 both), no truncation.
Recommendation: CONFIRM on 2 more names before switching the sweep, then adopt.**

Isolation verified byte-for-byte before any GPU time: `rs2-analyst-deep-mtp` has SYSTEM
byte-identical to `rs2-analyst-deep-q4`, both FROM blobs (main + draft head), and the ONLY
parameter difference is `draft_num_predict 4` — the treatment. Reasoning effort still reaches the
model through `RENDERER qwen3.8` (prompt tokens 5,973 / 5,935 / 5,937 at high / medium / off,
matching the twin token-for-token). Build details and the three traps in `faa8648`.

## Measurement — GOOG, think=high, ctx 81,920, identical pack

| arm | secs | output chars | ch/s | vs incumbent | quality |
|---|---|---|---|---|---|
| Q5 UD — **incumbent** | 1,374 | 99,324 | 72.3 | — | 4/4 |
| Q4, no MTP | 1,377 | 95,044 | 69.0 | −5% | 4/4 |
| **Q4 + MTP** | **771** | 92,499 | **120.0** | **+66%** | **4/4** |

Isolating MTP against its own twin (Q4 vs Q4+MTP) gives **+74%**. Against the incumbent it is
+66%, because Q5→Q4 costs ~5%.

**Two things this rules out.** Total output volume is within 2.7% across all three arms, so the
speedup is *not* the model writing less. And llama.cpp reports no truncation in either A/B arm,
so it is not truncation masquerading as speed.

**The +35% prior was too low, and predictably so.** It was measured on production at ctx 32,768
with thinking OFF. Long reasoning traces are more predictable token-for-token than terse output,
which is exactly the regime where a draft head's acceptance rate climbs. Measure the knob where
it ships.

## Quality — no regression found, and one improvement

All three arms score 4/4 on the discriminating checks. Going past the checklist to the substance
test that caught medium's failure (`K_effort_medium_vs_xhigh`), the ranking inverts against
expectation:

| arm | change in working capital |
|---|---|
| Q4 + MTP | `− ΔWC: $28.7B` **`[Actual – arithmetic]`** — read from the pack |
| Q5 incumbent | `$28.704B` `[Arithmetic]` — read from the pack |
| Q4, no MTP | **absent** — owner earnings given as "≈ $70–80B `[Estimate]`" with no ΔWC term |

MTP matched the incumbent and beat its own Q4 twin on data utilisation. The thinking/report split
did shift (48% thinking vs the twin's 70%, same total volume) — superficially the pattern that
accompanied medium's degradation — but here it came with *better* pack usage, not worse. On this
evidence the split is run-to-run shape, not a depth signal.

**The stale counter-finding is retired.** `SESSION_SUMMARY` records "Q4 truncates 4/6, Q5 0/6",
which argued against Q4. That was measured at the old 49,152 output budget; at the current 65,536
with ctx 81,920 neither arm truncated. It no longer bounds the decision in either direction.

## What this does NOT establish

- **n=1 name, n=1 run per arm.** No seed variation, so run-to-run scatter is unmeasured — and
  wall-clock scatter of ±8% was observed between arms in the effort A/B, though nothing near 66%.
- Not tested on a second name, and **not tested on a thin-data name** (a 2-year-history ticker
  like GRDN stresses different behaviour than GOOG's 12).
- Speculative decoding preserves the output *distribution* under sampling, not the exact sequence
  for a given seed. Adopting MTP therefore invalidates byte-reproduction against verdicts drawn on
  the current model; seeded determinism still holds *within* the new model.
- Q4 quantization was previously suspected on long-context arithmetic. One 4/4 name is not a
  clearance for that concern across 171.

## Recommendation

Run GOOG + 2 more names (one thin-data, e.g. GRDN or CART) through both arms before switching
`depth_model`. That is ~1 GPU-hour against a change that would touch every future verdict. If it
holds, the sweep goes from ~14 GPU-days to ~8.
