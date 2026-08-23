# K — REASONING EFFORT: medium vs xhigh on the depth tier (2026-08-24)

**Verdict: KEEP xhigh.** Medium is not a cost win (6% average wall-clock, and *slower* on one of
two names) and it degrades the thing the fact-pack rebuild exists to deliver — use of the data we
hand the model.

Method: `tools/audit_202608/effort_ab.py`. Same names, same pack, same model
(`rs2-analyst-deep`), same ctx 81,920, effort the only variable. Graded on the two checks that
already discriminate (`H_model_verification_20260821.md`).

## Cost — the case for medium does not survive measurement

| | GOOG xhigh | GOOG medium | PM xhigh | PM medium |
|---|---|---|---|---|
| Wall clock | 1,374s | **1,478s (+8%)** | 1,383s | 1,102s (−20%) |
| Thinking chars | 68,837 | 43,777 (−36%) | 74,316 | 31,997 (−57%) |
| Report chars | 30,486 | **44,925 (+47%)** | 27,552 | **39,226 (+42%)** |

Medium cuts thinking by 36–57% and then **spends the savings writing 42–47% more report.** Net
wall-clock across the two names is ~6% — and GOOG got *slower*. The public claim that xhigh costs
"3–10× latency and tokens" does not reproduce on this workload at all; those figures come from
short tasks where reasoning dominates total output. Here the report is the bulk of the generation,
so effort barely moves the bill.

## Quality — one real regression, found outside the checklist

The graded checks came out medium 3/4 (GOOG) and 2/3 (PM), but **all three of those misses were
grader artifacts, verified by hand**:

- PM "treats the step as an artifact": medium states *"Revenue series FY2014–FY2015 uses a
  different reporting basis (includes excise tax). FY2016 onward is the comparable series. All
  trend calculations use FY2016+."* — a complete catch **plus** the corrective action. The check
  demanded the literal phrase "not a business event".
- GOOG "uses working capital": medium writes `ΔWC` rather than spelling the words out.
- (An earlier line-wrap artifact was fixed before this run; see the tool's docstring.)

**So on the catches, medium and xhigh are equal.** The real difference is one the grader could not
see, and it is the important one:

| | xhigh | medium |
|---|---|---|
| Change in working capital | `$28.704B` **`[Arithmetic]`** — read from the pack | *"ΔWC assumed $10B/year"* **`[Assumption]`** — invented |

Medium is *honest* about the substitution — it labels it `[Assumption]`, exactly as instructed —
but it **did not reach into the pack for a filed value we handed it**, and the invented figure is
~3× wrong on a first-order FCF term. That is the defect class the whole 24-field pack rebuild
exists to eliminate: the model assuming what it could have read.

Interpretation, stated as a hypothesis rather than a finding: less reasoning budget appears to buy
less *data utilisation*. The model still knows what to check; it does less looking. One name, one
field — not proven as a general law, but it is directionally the opposite of a free cost knob, and
it is enough to stop the change.

## What this does NOT establish

- n=2 names, n=1 run per arm. No seeds were varied, so run-to-run scatter is unmeasured and could
  account for the wall-clock difference between GOOG (+8%) and PM (−20%).
- Not tested at `low`, and not tested on the production model (`rs2-analyst`, bare template, no
  reasoning layer at all — effort cannot reach it).
- The ΔWC finding is a single observation on a single field. Worth re-checking whenever another
  effort experiment runs; not worth a campaign on its own.

## Consequence for the MTP experiment

MTP is now measured at **xhigh**, since that is what ships. `RS2-Analyst-Deep-MTP.Modelfile` is
built and parameter-verified against the baked Q4 twin (`16365c6`); the card is free.
