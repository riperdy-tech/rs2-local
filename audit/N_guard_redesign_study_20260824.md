# N — THE PLAUSIBILITY GUARD UNDER A 3-SAMPLE BAND SYSTEM (2026-08-24)

Operator brief: the earlier one-paragraph fix was too minimal for how much this affects published
verdicts. This is the deeper study, calibrated on the 28 published verdicts and their 80 samples
rather than on the four GOOG reference points the guard was originally fitted to.

**Conclusion up front: sample rejection is the wrong mechanism for this system.** Under
band-direction the three samples ARE the uncertainty estimate. Deleting one does not remove
uncertainty — it hides it, and inflates apparent confidence. The guard should be reduced to
integrity tests and converted from a deleter into an annotator.

---

## 1. What the guard does today

`consensus_valuation.plausibility()` rejects a sample if its IV trips ANY ONE of four absolute
thresholds. A rejected sample is dropped from the band and the median; its report is still
written and published, only its vote is destroyed.

| constant | test | provenance |
|---|---|---|
| `BAND_LOW_DIV = 3.0` | IV below ⅓ of the PV'd analyst low | fitted to GOOG, 2026-08-20 (`9ba2929`) |
| `BAND_HIGH_MULT = 1.5` | IV above 1.5× the PV'd analyst high | same |
| `OCF_MULT_MAX = 40.0` | IV implying >40× TTM operating cash flow | same |
| `MOS_EXTREME = 1.50` | \|MoS\| > 150% | same |

All four were calibrated against **four reference points on one ticker on one day**, chosen so
that a known-bad value ($702.49) failed and three known-reasonable values passed. That is the
entire evidential basis.

## 2. What it actually does, measured across 28 verdicts

- **6 samples rejected.** All 6 **agreed with the surviving samples on direction**.
- **0 verdict directions changed.** Recomputing every verdict with the rejected sample restored
  leaves all 28 directions identical.
- Its only live effect is **narrowing bands**. AVGO is the clearest harm: deleting one sample took
  its spread from 64% to 2% and upgraded its position-size hint from *quarter* to **full**, on
  evidence that did not support it.
- Two rejections were decided by rounding: **AMD at exactly 40.0× against a 40× cap**, and ATI at
  $57.00 against a $57.88 floor.

**It is also nearly orthogonal to the real outlier signal.** Ranking every sample by divergence
from its own siblings, the guard rejected the single most divergent sample in the corpus (FIX s2,
3.04×) but *kept* the next three (AMZN 2.44×, GEV 2.29×, AGX 2.22×). It caught the top one by
coincidence, not by design.

## 3. Why absolute thresholds cannot work here, in one example

The OCF test asks: does the intrinsic value exceed 40× the cash the business currently generates?

| | rejected IV | its multiple | market price | the market's multiple |
|---|---|---|---|---|
| AMD | $247 | 40.0× | $473.25 | **76.6×** |
| AVGO | $350 | 49.5× | $368.45 | **52.1×** |

The guard called $247 "not backed by cash" while the market pays $473 at nearly double that
multiple. The test compares a **forward-looking value** to **trailing** cash flow, so it
mechanically penalises companies whose cash flow is growing — and it deletes the bullish tail
specifically, biasing high-multiple names toward "overvalued".

## 4. The measurement that decides the design

**The model's own disagreement with itself, on identical inputs, is large and normal.**

| | |
|---|---|
| Intra-name spread (max/min − 1), all 28 names | median **45%**, p75 95%, p90 143%, max 240% |
| A sample vs the median of its siblings | median 1.22×, p90 1.78×, p95 2.22×, max 3.04× |
| Sample IVs as a multiple of price | p05 0.30×, p50 0.85×, p95 1.34× |

Any threshold tighter than ~45% is cutting into ordinary variation rather than catching faults.

**And divergence does not indicate malfunction.** AMZN's most divergent kept sample ($104 against
siblings' $253, 2.44×) is a coherent, well-sourced bear case: it runs a reverse DCF, finds the
market price implies a 17–22% terminal FCF margin, and calls that excessive for the business mix —
citing filed data and labelling every assumption. Both it and its siblings are defensible views of
Amazon's terminal margin.

So a malfunction **cannot be identified from the value, nor from its distance from its siblings.**
This is what invalidates my own earlier proposal ("reject only on ≥2 trips plus a direction
change") — that rule still judged the number.

## 5. What changed structurally, and why rejection is now the wrong tool

The guard was designed for a **point-estimate** system: one published number per ticker, so a
single bad value became the answer, and deleting it was the only defence.

Under **band-direction** an outlier cannot do that. It widens the band; a wider band means a
larger spread; spread already drives the position-size hint down. **The system already penalises
extremity proportionally.** Rejection is a second, cruder, binary penalty applied on top — and it
destroys the very quantity the scheme uses to express doubt.

Test against the original malfunction: had GOOG's $702.49 arrived as one sample beside $300 and
$333, the band would be $300–$702 with the price ($343.54) inside it → **hold, enormous spread,
quarter size.** That is a correct and honest output. The band absorbs the malfunction without
needing the guard at all.

## 6. Proposed design

Keep the *purpose* — refuse to publish machinery output that is not a real valuation — but move
the test from the VALUE to its INTEGRITY.

**Reject a sample only when it is not a genuine, complete statement of the model's view:**

1. **Parse integrity.** The extracted number must be the value the report actually concludes with.
   This is the one class that has demonstrably destroyed real votes (ATI, AZN, CIEN — three
   samples lost to phrasing the parser did not recognise, each recoverable). Stronger fix: have
   the TASK prompt require one machine-readable `FINAL_IV: $N` line and parse that first, patterns
   as fallback.
2. **Completeness.** Empty report, stub report, or truncation at the output cap — the model did
   not finish stating a view. Already partly handled.
3. **Absolute impossibility.** Non-positive, or outside a deliberately wide envelope
   (`extract_iv` already filters 0.02×–10× of price). No calibration required, no judgment.

**Everything currently rejected becomes an ANNOTATION, not a deletion.** The four thresholds stay
computed and are recorded on the verdict as flags — e.g. `flags: ["ocf_multiple_49.5x",
"above_analyst_high_1.68x"]` — so the site can show *why* a band is wide, and so we retain the
data to re-derive thresholds later. Nothing is silently discarded.

**Coherence with the 3-sample scheme:** every sample that genuinely states a view contributes.
`n_basis` becomes 3 for almost every name; bands widen to their honest width; spreads reflect real
disagreement; and the size hint — which is the mechanism that already exists for expressing
low confidence — does the work the guard was doing badly.

## 7. Expected effect, measured

Applying this to the 28 published verdicts: **6 samples restored, 0 directions changed**, and 9
verdicts currently resting on fewer than 3 samples improve. The visible changes are all in the
direction of honesty — AVGO's spread returns to 64% and its size hint to quarter; ATI stops
publishing a single-point band as though it were consensus.

## 8. Open, and NOT resolved by this study

- **The size-hint buckets** (`SIZE_BUCKETS` 15%/30% → full/half/quarter) were themselves set
  before any spread data existed. Median spread is 45%, so today almost everything lands in
  "quarter". They need re-deriving from the observed distribution — but only once the full book
  is measured, not now.
- **Whether high intra-sample disagreement should itself reduce conviction further**, beyond the
  size hint, is a portfolio question, not a guard question.
- This study measures 28 names. The full sweep will give 171, and the thresholds — if any survive
  as flags — should be re-derived from that population.

**Recommend applying §6 after the sweep completes**, not mid-run: it changes the composition of
published bands, and mixing two guard regimes within one book would make the results
uninterpretable.
