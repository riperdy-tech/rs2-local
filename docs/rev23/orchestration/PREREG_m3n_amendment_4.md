# PREREG_m3n amendment 4: reviewer 2 after Gemini's quota ran out (2026-10-29)

**When it was written:** during N4, before any truth file was frozen and before any 3N model run.

## What happened

Reviewer 2 (Gemini 3.8 Flash through `agy`, plan mode, blind) completed **46 cases**:
- C1: 1–12;
- C2: 1–32, in part;
- C3: 1–4;
- C5-109.

Then every call failed with `RESOURCE_EXHAUSTED (code 429): Individual quota reached ... Resets in 141h53m`. Waiting six days would stop 3N. The operator's standing rule is to proceed without waiting, and Sonnet is the recorded fallback when Gemini's quota runs out.

## What Gemini's 46 cases showed (kept as evidence, and resolved in `m3n/adjudication/resolutions.jsonl`)

5 disagreements, all in C2:

| Case | Resolution |
|---|---|
| SBLX | r2 right: a new doubt (r1's tagger had miscounted a historical sentence) |
| RANI | neither: prior-year auditor report only |
| LITE | conditional |
| REFR | unknown |
| VII | unknown |

C2 is where reading needs the most care, and reviewer 2 caught a real reviewer-1 error. That is why reviewer 2 continues.

## The amended rule

1. **Who.** Reviewer 2 continues as **Claude Sonnet 5.5 subagents** ("r2s"), each fresh and blind: given only `REVIEWER2_BRIEF_m3n.md` and its case folders, and told not to open `r1/`, `r2/`, `adjudication/` or `queue/`. Being the same model family as reviewer 1 weakens independence; that is stated here and in the report.
2. **Full second review** of:
   - every case reviewer 1 labelled `confirmed_critical`, `confirmed_noncritical`, `unknown`, `out_of_window` or `insufficient_evidence`;
   - every case of C1 to C4 up to the class's last sampled event;
   - all 24 DEV controls.
3. **A seeded 20% sample** of reviewer 1's `non_event` cases in C5 to C8. Seed `m3n-2026-10-29/r2sample`, drawn per class.
   - **If the sample finds any reviewer-1 miss** (a `confirmed_critical` that reviewer 1 called `non_event` and that the resolution upholds), every `non_event` of that class up to its last sampled event is second-reviewed.
4. **Cases Gemini already finished** keep Gemini as reviewer 2.
5. **Disagreements** are resolved by Claude with a written reason, as before. The truth label is the resolution where one exists, otherwise the agreed label.
