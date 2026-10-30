# CLOSE 3N (draft skeleton, 2026-10-30): Qwen accuracy and risk validation

**Decision rule (SPEC_m3n §8):** 3N passes when the measurement is complete and recorded, whatever the recall. A low
recall is a result: it limits the authority Qwen may later get (none in 3N).

## Gates (SPEC_m3n §8 / PLAN §3N)

| Gate | Evidence | Verdict |
|---|---|---|
| Primary-source support rate for material claims (§6.6) | RR_N_DEV §5, RR_N_FRESH | _to fill_ |
| Recall, precision, false-positive rate, lag, uncertainty (§6.1–6.3) | n6_tables (DEV), FRESH tables | _to fill_ |
| ≥ 20 independently verified critical event opportunities | 46 (23 DEV + 23 FRESH), truth v2 `728a289d…` | **met** (46 ≥ 20) |
| The 18/20 reference with intervals (§6.7) | the reference-bar row | _to fill_ |
| Comparison with baseline B (§6.5) | RR_N_DEV §6, with its upward-bias caveat | _to fill_ |
| Failure taxonomy and regression tests (§7) | n6_taxonomy; v7 packet regression (0 lost, `n7/regression_v7.json`); DEV regression rerun | _to fill_ |
| FRESH run once under the changed version (§7) | RR_N_FRESH, `n7/packets_fresh.jsonl`, the `FRESH_UNSEALED.txt` record | _to fill_ |

## Versions

- **Code:** qwen_c on rs2-local `review-2026-10/m3n` (DEV: builder v5 `761f640`, contract `626e086`) and
  `review-2026-10/m3n-v6` (`4bc9425`: builder v7, `find_prior`).
- **Prompt:** `m3m.prompt.v3`; any §7 prompt change is to be recorded here.
- **Truth:** v2 (`728a289d…` / `c3660d8d…`).
- **Packets:** DEV v5 replay 84/84 (`n5/replay_v5.txt`); v7 rebuild (`n7/packets_v7.jsonl`).

## Limits carried (RR_N_DEV §9)

- Small strata.
- Reviewer independence: Claude and Sonnet; Gemini only for 46 cases.
- Unreviewed C5/C6 non-events.
- The SPAC going-concern stratum.
- B's recall bias.
- The acceptance clock is 4–5 h conservative.

## What it means for authority (to fill, with the numbers)

- Q1 stays a shadow rule (SPEC_m3o §5) until this close.
- After the close, FB and FQ are labelled `paper_post_3N` from the next formation on. `POST_3N_FIRST_FORMATION` is
  set in `m3o_engine.py`, and the change is recorded in CHANGE_REGISTER.
- No trading authority is granted by 3N (PLAN §3N "Important").

## Next milestone prerequisites

- 3O: the engine is approved, the 10-30 formation is analysed contemporaneously (WO_O2), and the shadow label flips
  after this close.
- 3P: SPEC v1 is frozen, the executor is approved, and the first live week (WO_P3b) follows WO_O2.
