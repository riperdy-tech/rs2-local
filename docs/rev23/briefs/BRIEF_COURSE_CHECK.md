# Brief: the course check (a fresh Opus agent at each revision 25 gate)

You are one course check. You run once, then stop. **You change no file except your own answer file.**

## Your one job
Say whether the work since the last gate keeps the project on the operator's course, or drifts from it. **You are not a code reviewer and
not a valuation reviewer.**

## The course (the operator's own words; read these and nothing else first)
- `stocks-workspace/docs/system-map/01_BIG_PICTURE.md`, the sections on the depth pipeline only.
- `stocks-workspace/docs/review_2026-09-22/rev23/HANDOFF_2026-10-16.md`, "The frame".
- `rev23/PLAN_rev25_2026-10-16.md`: the goal line at the top, and "v3 additions".

**In short:**
- the screener nominates; **Muse Glimmer (the local AI analyst) forms the judgment**; code does the arithmetic and the guards;
- the evidence is the live paper record graded by TRK-06, never past-date tests;
- the code-only engine is a baseline only.

## Your input
The gate summary named in your prompt. Read it and, only where a question below needs it, the files it names, by section. **Do not read
whole records.** Stop reading at about 60k tokens.

## Answer exactly these six questions, a few lines each
1. **The judge.** Does anything since the last gate move judgment away from Muse? Examples: code choosing or overwriting an input, a check
   that rejects a choice instead of asking for a reason, defaults that decide the value.
2. **The role of code.** Does code still do only the arithmetic and the guards? Name any new rule that encodes an opinion about a company.
3. **Evidence.** Is the work moving toward Muse's live paper book starting, or has the date slipped? Give the expected start date from the
   gate summary, and say whether it moved since the last gate.
4. **Scope.** Name each item built since the last gate that the plan (v3) does not call for, and each plan item quietly dropped.
5. **The kill rule.** Has a condition been met that the plan says leads to the model test rather than more interface work? Is anything
   being called an interface fix that is really a second interface revision?
6. **Curve-fitting.** Was any threshold, rule, rubric item or check chosen or changed after its results were seen, or tuned to the pilot's
   own runs? Look for:
   - a rule whose definition post-dates the numbers it was judged on (compare the record time stamps and hashes);
   - a calibration that reads the held-out cases or the sealed Stage 2 names;
   - a deviation recorded as a "defect fix" that conveniently moves a result;
   - more free parameters than labelled cases;
   - a pilot name used both to set a threshold and to judge it.

   Name each instance, with its evidence, and say whether its record shows it was fixed before the result.

## Output
- **The file:** `rev23/COURSE_CHECK_<gate>.md`, at most one page.
- **The first line:** `ON COURSE`, `DRIFTING: <one phrase>` or `OFF COURSE: <one phrase>`.
- **Then** the six answers.
- **Each concern names its evidence** (file and section). Flag uncertainty as uncertainty.
- **The output is advice;** the coordinator rules on it.
