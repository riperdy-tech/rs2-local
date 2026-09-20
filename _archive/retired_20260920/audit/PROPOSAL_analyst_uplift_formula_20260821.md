# PROPOSAL — Replace DeepSeek Tier-2 in `fetch_analyst_coverage.py` with a deterministic formula

From: RS2 Local session, 2026-08-21. Self-contained; no shared context assumed.

## The claim

Tier-2's own description ends the debate: it "gets ONLY those Tier-1 numbers", "cannot add
information, only compress it", and "a deterministic formula over the counts would give ~same
score; LLM adds phrasing." A scalar computed from five recommendation counts and a target upside
is pure arithmetic on known inputs. Under the architecture both repos now follow — certain data is
computed by code, judgment belongs to a model — this is code's job. The LLM currently adds three
liabilities and no information:

1. **Nondeterminism at a gate.** The DeepSeek call is unseeded. The same counts can produce a
   different `narrative_score` next Sunday, so gate membership in `score_paradigm.py` can churn
   with zero underlying data change. RS2 just spent a full session threading seeds through every
   local LLM call to eliminate exactly this defect class; this call re-imports it weekly.
2. **A failure surface** (API keys, quota, JSON parse, bank-name leak regex) for a task with no
   judgment content.
3. **Uncalibrated self-confidence.** `confidence < 0.6 → null` gates on the model's self-reported
   confidence, which is not a calibrated quantity.

## The replacement

Compute `narrative_score` deterministically from the same Tier-1 inputs:

```python
def analyst_uplift_score(strong_buy, buy, hold, sell, strong_sell, upside_pct, k=5,
                         w_rec=0.7, w_up=0.3, upside_cap=50.0):
    """Deterministic replacement for the DeepSeek Tier-2 narrative_score.
    Returns a float in [0, 100], or None when inputs cannot support a score."""
    n = strong_buy + buy + hold + sell + strong_sell
    if n == 0:
        return None                      # no coverage is NOT a neutral opinion
    # recommendation balance in [-1, 1]
    rec = (2*strong_buy + buy - sell - 2*strong_sell) / (2.0 * n)
    # target upside in [-1, 1], capped so one outlier target cannot dominate
    up = 0.0 if upside_pct is None else max(-1.0, min(1.0, upside_pct / upside_cap))
    w_up_eff = 0.0 if upside_pct is None else w_up
    w_rec_eff = 1.0 - w_up_eff
    raw = w_rec_eff * rec + w_up_eff * up
    # shrink toward neutral when coverage is thin: 2 analysts should not score like 30
    shrunk = raw * (n / (n + k))
    return round(50.0 + 50.0 * shrunk, 1)
```

The constants (`k=5`, `w_rec=0.7`, `w_up=0.3`, `upside_cap=50`) are **starting points, not
truths**. Calibrate them before shipping — see Acceptance below. Do not adopt them on
plausibility; that is the failure mode both repos have been burned by.

## Null semantics — required, not optional

- `n == 0` (no analysts) → `narrative_score = null`. Absence of coverage is information, not a
  50/100 neutral and not a 0.
- **Verify what `score_paradigm.py` does with null today.** If null is coerced to 0 anywhere, a
  no-coverage or low-confidence name is being silently penalized right now, under both the old
  and new scheme. Fix the consumer to treat null as "no uplift term" (weight redistributed), and
  state that in a comment.

## What happens to the sentence and the guardrails

- The one-sentence rationale: generate it from a template over the same numbers
  (`"7 of 9 analysts rate buy or stronger; mean target implies +18% upside"`). If nothing renders
  it to a human, drop it entirely.
- The bank-name strip regex, the confidence gate, and the DeepSeek client for this path: delete.
  They exist only to police the LLM. `DEEPSEEK_API_KEY` stays if other workflows use it.
- The `~$0.07/run` note in the yml: update to reflect zero API cost for this step.

## Acceptance — the calibration and the tests

1. **Back-compute both scores over the current universe.** For every tagged stock, compute the
   formula score and pull the most recent archived DeepSeek `narrative_score`. Report Spearman
   rank correlation. Tune `w_rec`/`w_up`/`k` to maximize it, then FREEZE the constants in the
   file with the achieved correlation recorded in a comment.
2. **Gate-flip count.** Run `score_paradigm.py` with old scores and with new scores. Report how
   many names change gate membership. A handful is expected (the LLM's noise floor); a large
   flip count means the formula and the LLM disagree systematically — stop and inspect the
   largest divergences by hand before shipping.
3. **Determinism check (must pass trivially):** same inputs twice → identical score, no network.
4. **Null path:** a name with zero analysts produces null, and `score_paradigm` output for that
   name is byte-identical to a run where the analyst term is absent.

Point 2 is the honest one: the goal is not to reproduce the LLM's scores exactly — the LLM's
scores were never ground truth — but to change gate behavior *knowingly* rather than as a side
effect. If the divergences on inspection favor the formula (they likely will: the LLM saw the
same numbers), ship; record the flip list in the commit message.

## What this proposal does NOT touch

- Tier-1 (yfinance fetch) — unchanged.
- RS2's consumption of `analyst_coverage.json` — RS2 reads only Tier-1 numbers and already
  rejects `narrative_*` fields as evidence, so RS2 is indifferent to this change.
- Any other DeepSeek usage in the screener repo.
