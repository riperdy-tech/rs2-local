# CLOSE 3N: 2026-10-31

**Decision: PASS.** SPEC_m3n §8 passes the milestone when the measurement is complete and recorded, whatever the recall.
It is complete.

- **What 3N measured:** on 46 SEC-verified material events after the model's knowledge cutoff, does Qwen report what the
  record shows, and how often does it report what did not happen?
- **What it grants:** no trading authority (PLAN §3N "Important").
- **What it changes:** FQ and FB lose the `shadow_pre_3N_close` label from the next formation, 2026-11-30. They become
  `paper_post_3N`. Rows already recorded are never relabelled.
- **Who closed it:** Claude, under the operator's standing go of 2026-10-29 to close 3x milestones.

## Gates (SPEC_m3n §8 / PLAN §3N)

| Gate | Evidence | Verdict |
|---|---|---|
| Primary-source support rate (§6.6) | DEV v7: detecting claims 0.90 / 0.95; FRESH 0.86 / 0.96 (seeds 1000 / 3000) | **reported** |
| Recall, precision, false-alarm rate, lag, uncertainty (§6.1–6.3) | RR_N_DEV §5, §8a, §8b; RR_N_FRESH §2. FRESH strict recall 0.82 / 0.91, lenient 0.95; precision 0.94; median lag 2 sessions; κ 0.24 | **reported**. FRESH has no controls; the control false-alarm rate is DEV only (2/9, 4/9). This is recorded as a shortfall |
| ≥ 20 independently verified critical event opportunities | 46 events: 23 DEV and 23 FRESH. Truth v2 `728a289d…` | **met** |
| The 18/20 reference with intervals (§6.7) | FRESH: seed 1000 0.82 (0.61–0.93) not met; seed 3000 0.91 (0.72–0.97) met at the point | **reported** |
| Comparison with baseline B (§6.5) | FRESH McNemar p = 0.69 (B only 4, Qwen only 2); DEV p = 0.375. B is biased upward by construction | **reported** |
| Failure taxonomy and regression tests (§7) | RR_N_DEV §8; v7 packet regression (0 lost); DEV regression rerun 212/212 (§8b); FRESH taxonomy (RR_N_FRESH §4) | **reported** |
| FRESH run once under the changed version (§7) | `n7/FRESH_UNSEALED.txt` (10-30 13:36Z), 128/128, scored once by `n8_score_fresh.py` | **done** |

## Versions

- **Code:** qwen_c on rs2-local `review-2026-10/m3n-v6`:
  - `4bc9425`: builder v7 and `find_prior`;
  - `15207e4` and `d2f3f15`: contract v3.
- **Prompt:** `m3m.prompt.v3`.
- **Model:** `rs2-analyst-deep-mtp5-v33`.
- **Truth:** v2 (`728a289d…` / `c3660d8d…`).

## Carried to the follow-up list (not fixed in 3N)

1. **Compound designators** (RR_N_FRESH §4). "Case No. 26-11399" and "Rule 5550(b)(1)" are rejected as unlisted figures. They
   caused 3 of the 4 strict misses at seed 1000. Any fix is a second §7 change, so its fresh number needs FRESH-2.
2. **No FRESH controls.** A FRESH-2 draw should include controls.
3. **The output-length cap** (`num_predict`) for long packets (RR_N_DEV §8 c).
4. The RR_N_DEV §9 limits.

## What it means in plain words

- **Finding events:** when a company files something critical, such as a bankruptcy, a going-concern doubt or a delisting
  notice, Qwen reads the filings and names it about 19 times in 20.
- **The strict check:** the code double-checks every number and quote. It passes 4 to 5 of those detections in 5. Most of
  the rest it rejects because of how a reference number is written, not because the model was wrong.
- **Warnings beyond the event:** when Qwen warns about some other critical event, it is right 94% of the time.
- **Authority:** this is enough to treat its warnings as a measured paper signal from the November formation. It is not
  enough to let it trade.
