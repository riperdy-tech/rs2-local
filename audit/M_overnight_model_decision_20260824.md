# M — OVERNIGHT MODEL BATTERY: which model runs the depth tier (2026-08-24)

Operator brief, 00:00: test the candidates, narrow to two, spend the night testing those two,
conclusive answer by 07:30.

---

## THE NARROWING — done by reading metadata, not by burning GPU

The field looked like four arms (Q5 / Q4 / Q4+MTP, and a hypothetical Q5+MTP that HuggingFace
searches suggested might not exist). Checking the local blob settled it in seconds:

```
rs2-analyst-deep   qwen35.nextn_predict_layers = 1
                   qwen35.block_count          = 65      (64 repeating + 1 nextn)
                   tensors: nextn.eh_proj / enorm / hnorm / shared_head_norm
```

**Qwen3.8 bakes the MTP head into every quant, Unsloth Dynamic included.** All three local deep
models carry it. MTP is therefore **a parameter (`draft_num_predict`), not a quantization
choice** — which retires the framing in `audit/L`, my own document from four hours earlier, that
sold this as a quality-for-speed tradeoff. There is no tradeoff: Q5+MTP dominates Q4+MTP (same
head, better weights), and Q4 measured 5% *slower* than Q5 anyway.

Two finalists, and the two dead branches cost zero GPU hours.

**Isolation, verified before any run:** `rs2-deep-q5base` vs `rs2-analyst-deep-mtp5` — SYSTEM
byte-identical at 21,310 chars, both Q5_K_M, both `nextn_predict_layers=1`, and the *only*
parameter difference is `draft_num_predict 4`. A matched baseline had to be built because
ollama's Modelfile parser normalises the CRLF the incumbent tag bakes — a 463-character confound
that would otherwise have ridden along as a second variable.

---

## SPEED — unambiguous, and the distributions do not overlap

Five names, one run per arm, `think=high`, ctx 81,920, identical packs.

| ticker | q5 | q5+mtp | gain |
|---|---|---|---|
| GOOG | 58.3 | 98.1 | +68% |
| PM | 57.1 | 114.9 | +101% |
| CART | 57.0 | 100.7 | +77% |
| GRDN | 56.7 | 92.8 | +64% |
| AVGO | 57.1 | 115.5 | +102% |
| **median** | **57.1** | **100.7** | **+76%** |

q5 spans 56.7–58.3 ch/s (n=5); q5+mtp spans 92.8–115.5 (n=6). **The worst MTP run is still 59%
faster than the best Q5 run.** No overlap, so the speedup does not depend on which run you draw.

The +35% prior was measured on production at ctx 32,768 with thinking OFF. Long reasoning traces
are more token-predictable than terse output — exactly the regime where draft acceptance climbs.
Measure the knob where it ships.

---

## DRAFT TUNING — inconclusive, and the honest answer is to keep 4

| draft_num_predict | secs | ch/s | checks |
|---|---|---|---|
| 2 | 865 | 98.7 | 4/4 |
| 4 | 1,168 | 98.1 | 4/4 |
| 6 | 1,201 | 94.9 | 3/4 |
| 8 | 813 | 120.2 | 3/4 |

Tempting to read 8 as fastest. **It is not distinguishable from noise:** GOOG on a *fixed*
setting scattered 94.9–120.2 ch/s across five runs — a 27% spread that swallows the entire range
of the tuning table. Each draft value has n=1. Keep the shipped 4; revisit only with n≥3 per
value, which this window could not afford alongside the quality work.

---

## QUALITY — four names identical, one name is the whole decision

| ticker | q5 | q5+mtp |
|---|---|---|
| GOOG | 4/4 | 4/4, 4/4 |
| CART | 3/3 | 3/3 |
| GRDN | 3/3 | 3/3 |
| AVGO | 3/3 | 3/3 |
| **PM** | **2/3** | **1/3** |

PM carries the fake −64% revenue collapse (FY2015→16 excise-tax basis change) that the pack's
continuity warning exists to defuse. Reading the reports rather than the checklist:

- **q5**, line 550: *"2015/2016 revenue basis change excluded from trend: Pass"* — caught it.
- **q5+mtp**: the word "excise" appears once, in an unrelated risk bullet. The discontinuity is
  **never addressed**. Its 1/3 is itself a false pass — the checklist matched that stray word.

*(Checklist caveat, stated because it has bitten three times this session: these regexes have
produced false MISSES on line-wrapped phrasing and, here, a false PASS on an incidental word
match. Every quality claim above was confirmed by reading the report.)*

<!-- PM_REPLICATION -->

---

## WHAT THIS DOES NOT ESTABLISH

- One run per arm per name outside GOOG and PM. Speed is safe at that n (no overlap); quality is
  not, which is why PM got replicated and the others did not.
- Adopting MTP invalidates byte-reproduction against verdicts already drawn on the incumbent.
  Speculative decoding preserves the output *distribution* under sampling, not the per-seed
  sequence. Seeded determinism still holds *within* the new model.
- `draft_num_predict` is untuned in any meaningful sense (see above).
- The 24 verdicts already on the site were produced by the incumbent. Switching mid-book means
  the overlay mixes two models until the next full pass.
