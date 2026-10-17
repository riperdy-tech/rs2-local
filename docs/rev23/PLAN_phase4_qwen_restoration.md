# Plan: restoring the Phase 4 analyst, Qwen, on the corrected desk (2026-10-17)

Agreed with the operator, question by question, on 2026-10-17.

## Where Phase 4 stood
1. **AT10c passed** on 2026-10-04 with Qwen v33 on revision 21. The design was frozen.
2. **The Phase 6 baseline** (10-04 to 10-06) found the verdicts unusable as valuations:
   - growth stocks at 0.2–0.45× price, cyclicals at 2–3.7×;
   - Qwen copied the code's reference value (within 10% in 11 of 19), and the reference formula itself carried directional defects
     (`rev23/defect_census.md`).
3. **The rebuild then moved to Muse and engine v2** (gates failed). Revision 24 fixed the desk:
   - the reference is withheld;
   - the RONIC floor is removed;
   - working capital is normalized;
   - the margin path follows D2–D4;
   - population ranges are added.
4. **Ollama 0.40.3** (auto-updated on 2026-10-11) silently broke Qwen's nested tool arguments. Option 3, the `ollama_raw` provider (rs2
   `141c413`), fixes it and serves Qwen at 60–76 tokens/s.
5. **Revision 25 on Muse did not pass Stage 1.** The operator has ruled Muse out of further use and comparison.

## The decisions
| # | Decision |
|---|---|
| 1 | **"Restore Phase 4"** means Qwen back as the analyst on today's corrected desk, not a reproduction of revision 21 |
| 2 | **The desk is revision 24** (pilot arm `iii_no_p50`: reference withheld, P50 omitted), not the revision 25 bridge. No comparison with Muse. This supersedes plan v3's "model test on the frozen revision-25 interface" |
| 3 | **The model:** Qwen 3.8 27B Q5_K_M with MTP and charter v3.3 (`rs2-analyst-deep-mtp5-v33`, the frozen Phase 4 tag), through Ollama via `ollama_raw`, think "high" |
| 4 | **Two runs:** MSGE (its frozen pack, research and evidence) and **one new company** never seen, hash-drawn (below) |
| 5 | **Discovery briefs are written by Qwen** for both names. MSGE's Muse-written brief is replaced; the research brief stays `rs2-research` |
| 6 | **One run per stock.** The operator dropped Phase 4's two-runs-per-stock rule ("takes way too long") |

## The new company, fixed before the draw
- **The pool:** the screener-publish nominations (2026-10-15T17:44:03Z), minus every name seen so far. That is the 8 Stage 1 names, the 6
  pilot names, KSS, HRTG and the 3 sealed Stage 2 names (excluded by the script, never displayed).
- **The order:** ascending sha256("phase4-restore:" + ticker).
- **The positive-earnings rule:** the first name whose base fiscal year has positive filed earnings (`x_L` > 0) is used, checked at the
  data stage. A name that fails passes to the next in order. That is recorded, never chosen by hand.

## Pass criteria per run, fixed before the runs
**Must pass:**
1. At least one complete desk run (Base, Bull and Bear valued), with no lost nested arguments.
2. No runner defect; a parsable contract with all fields.
3. Any directional call rests on a verified crux.
4. **Not incoherent** under rubric (c) of `REGISTRATION_rev25_stage1.md`, on the masked memo. Questionable is allowed.

**Reported, never pass or fail:**
- the value against the withheld reference and against consensus, flagged when within 5% (the Phase 4 copying signature);
- the refused calls, minutes and tokens per second.

**The decision rule:**
- both runs pass 1–4: a small verification set, sized with the operator;
- a fail on 1–3: plumbing; fix it and re-run that one run;
- a fail on 4: stop and review with the operator.

## Build before the runs
The Stage 1 runner's Qwen mode (brief G) is updated to:
- run the tree at rs2 `141c413` with `depth_provider` "ollama_raw" and `depth_model` `rs2-analyst-deep-mtp5-v33`;
- treat Ollama's own runner (`lib/ollama/llama-server.exe`) as ours in the guard;
- run arm `iii_no_p50` only;
- run stage P for the new name, with discovery on Qwen;
- regenerate MSGE's discovery brief with Qwen, keeping its research and evidence.

## The verification set (2026-10-17 18:06; the operator: "do 5. no need to wait overnight.")
- **The names:** the next 5 of `DRAW_ORDER.json` after TASK, in order, with positive base-year earnings, under the same pass-over rule. MSGE
  and TASK are not re-run.
- **The runs:** one per name, with the same model, desk, provider and discovery-on-Qwen as the first two runs.
- **The per-run criteria** are 1–4 above.
- **The set passes** when:
  - **at least 4 of 5 runs pass all of criteria 1–4** (the operator's margin of error);
  - **and no run has a directional verdict on an unverified crux.**
- **Reported, never pass or fail:**
  - the copying signature, flagged when within 5% of the reference or consensus;
  - minutes per run;
  - memo-against-verdict mismatches, after TASK's.
