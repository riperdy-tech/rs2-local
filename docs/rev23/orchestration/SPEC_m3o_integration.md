# SPEC 3O: factor + Qwen paper decision engine, v1.1, 2026-10-29 (v1.1: CROSS_CHECK_O rulings)

**Status:** written by Claude while the 3N DEV GPU run was still executing, before any 3N score was computed.
**Authority:** paper only. Nothing here changes the screener, the depth overlay, `rn_depth`, KIS, a schedule or a
deployment. `KIS_HALT`, `DEPTH_PAUSED` and `model_release_blocked=true` stay. SENEA, SENEB, MOV and MG stay excluded.
**Linked:** PLAN §3O; SPEC_factor_led_v2 §§1–5; PROTOCOL_factor_ai_m2 §§5–7; SPEC_m3m (qwen_c); SPEC_m3n and
PREREG_m3n (baseline B, the event classes); RR_L7 (the A0 forward ledger).

## 0. Disclosure before registration

Before writing this, Claude had seen:
- the A0 forward mark at 2026-10-27 (RR_L7: A0 +1.13% net at 20 bp, SPY +0.69%, one open month);
- 3N DEV model output: during S4/S5 adjudication, the other-class and control claims of 157 material_events
  claims (seed 1000 complete, seed 3000 partial), and partial interim scorer output used only to validate the scorer.

No rule below was chosen to fit any of these. No 3N recall, precision or false-alarm number exists yet. The rules are
deliberately the simplest ones the earlier records already imply (SPEC_factor_led_v2 §4, the 3N class definitions).

## 1. What 3O builds, and what it does not claim

**Builds:** one paper decision engine that, at each A0 formation, keeps four records apart:

1. the factor evidence (the witnessed screener run and its book);
2. the Qwen analysis (qwen_c run ids and manifests);
3. the verification (contract support results; baseline-B hits);
4. the resulting paper action per arm, with its rule id and reason.

It then computes the arms' paper return series on matched dates, prices and costs.

**Does not claim:** any skill. At close, 3O has at most two or three formations (09-30 retrospective, 10-30 and 11-30
contemporaneous). Performance comparison accrues in 3S. Insufficient duration is reported as `not_yet_validated`.

## 2. Arms (matched: same formations, fill sessions, prices, cost scenarios 0/20/60 bp)

| Arm | Book at formation T | Status |
|---|---|---|
| **F** factor-only | A0: the verified run's `research_now` names, equal weight, next-session adjusted-open fill (forward_ledger.py, unchanged) | running since 2026-09-30; **the paper book of record** |
| **FB** factor + deterministic text rule | F minus names with a B restriction (§3.1) | new; shadow measurement series (§5) |
| **FQ** factor + B + Qwen | F minus names with a B restriction or a Q restriction (§3.2), minus names in `analysis_pending` / `analysis_incomplete` (§3.3) | new; shadow measurement series (§5) |

**Analysis series (not an arm):** `FQ_decisions_only` is FB plus the Q1 restrictions, with pending and incomplete names
filled exactly as in FB. FQ − FQ_decisions_only is the operational cost of Qwen latency and failure. FQ_decisions_only
− FB is what Qwen's decisions add (CROSS_CHECK_O 3a).

**Start (v1.1, CROSS_CHECK_O 3b):** FB, FQ, FQ_decisions_only and the matched F series start at the 2026-10-30
formation, from cash; every name is then a new entry. The 2026-09-30 retrospective analyses are a separate one-period
series, `retrospective_2026-09-30`, and never a predecessor book.

**No A1 arm (v1.1, CROSS_CHECK_O 5).** PROTOCOL_factor_ai_m2 §4 allows prospective paper observation of A1 only if A1
passes all its bars, and A1 failed (1.6311x vs 1.60x). So no A1 book is run. PLAN §3O item 4 (quarterly rebalance,
drifted weights, cash, splits, delistings, costs) is met by the engine's book accounting, tested on fixtures. PLAN item
3: no new low-turnover candidate is registered in 3O.

FQ is built on FB so that FQ − FB isolates what Qwen adds over the deterministic floor (SPEC_factor_led_v2 §5, "C versus
B"). The model can add restrictions to the floor; it can never cancel one (the 2026-10-01 follow-up ruling).

## 3. Rules (preregistered; frozen in PREREG_m3o.json)

### 3.1 B restriction (rule `B1`)

B1 is a deterministic text rule, not SPEC_factor_led_v2 §3's verified-event checker: it checks neither status nor
supersession, and it is never called "verified" (CROSS_CHECK_O 8b). A name is B-restricted at T when baseline B (the 3N patterns, PREREG_m3n.json sha `eafda743…`, read by `baseline_b.py`
unchanged) hits any evidence item of the name's formation packet whose SEC acceptance is within 180 days before T.
Classes C1–C8 all count. The hit, its class, accession, pattern and passage are recorded.

### 3.2 Q restriction (rule `Q1`)

A name is Q-restricted at T when its qwen_c `material_events` task at T returns at least one claim with:
- an `event_type` that maps to one of C1–C8 (PREREG_m3n `accepted_event_types`);
- `support == "supported"` under the contract code of the run (the source verification of PLAN §3O item 6);
- `status == "announced_pending"`, or `status == "occurred"` with a **verified** `occurred_on` within 180 days before T.

`occurred_on` is a free string, and the contract does not check it (`contract.py:14`). So the engine verifies it
(v1.1, CROSS_CHECK_O 2a/2b):
- **Verified:** it parses as a date (forms "Month D, YYYY", "Mon. D, YYYY", "D Month YYYY", "YYYY-MM-DD"), and the
  same (year, month, day) is printed in at least one cited item.
- **`undated`:** a missing or unparseable date.
- **`date_unsupported`:** a date that no cited item prints.
- Neither of the last two acts. Each becomes an `escalation` line: logged, queued for 3P reanalysis, with no change to
  any series (SPEC_factor_led_v2 §4: "uncertain material claims [go] to an escalation queue").

Nothing else Qwen writes acts. The `risks`, `growth_thesis`, `thesis_change` and other task outputs are logged and
shown, never acted on (SPEC_factor_led_v2 §1: no veto by prose). An unsupported critical claim is logged as
`unsupported_critical_claim` and does not act.

### 3.3 Analysis states (rule `A1S`)

- `complete`: the run's `material_events` task status is `ok`. The name is eligible for FQ. If the run's overall status
  is not `complete` (another task failed), the name is flagged `partial_analysis`.
- `analysis_pending`: no completed run by the fill session's open. The name's equal-weight slot is held as **cash** in
  FQ and entered at the first session open after the run completes (adjusted open), if it is not Q-restricted.
- `analysis_incomplete`: the runner's two attempts both failed or the task is `malformed`. The slot stays cash in FQ
  until the next formation. It is never silently filled with a factor-only entry.

Cash, rather than redistribution, is used for these two states so that the operational cost of Qwen latency and failure
shows in the FQ series. It is reported separately as `cash_drag_pending` and `cash_drag_incomplete`.

### 3.4 Effects (rule `E1`)

- **Restricted, not held by the arm at T−1:** `new_entry_restricted`. The name is not entered. Its weight is
  redistributed equally over the arm's entered names (the book is equal weight over fewer names).
- **Restricted, held by the arm at T−1:** `pending_reunderwriting` flag; the name is **held** at its equal weight.
  No paper sale is caused by B or Q (monitoring never sells; forced-exit policy is operator-reserved, SPEC_factor_led_v2
  §6).
- **Exit:** a name leaves FB/FQ only when it leaves A0's book, exactly as in F.
- **Expiry:** each restriction lasts until the next formation, where it is re-derived from that formation's packet and
  run. The 180-day window bounds any pause from one dated event to about six formations.
- **Zero and missing:** a 0.0 weight, return or price is a value; missing is logged as missing.

### 3.5 Operator-excluded tickers

SENEA, SENEB, MOV and MG are never analysed. In FB and FQ their action is `operator_excluded`, and their weight
is redistributed as for a restriction. F keeps them as published (A0 records what the screener published), and F is
also reported without them, as in RR_L7.

### 3.6 Corporate actions and missing prices

As forward_ledger.py: Yahoo adjusted prices carry splits and dividends; a name with no bar is held as cash at 0% and
flagged `no_price_series` with its dates (the TBPH case). The flag routes to 3P/3R for an event source; it is never
resolved by a guess. These rules are identical across all arms.

## 4. Decision time and evidence

- **T** is the witnessed `updated_at` of the decision run that forward_ledger.py selects (the last verified scoring run
  before the fill session's open).
- **Packets:** regime `verified` (qwen_c `packet.py`, SPEC_m3m, as in M-LIVE): the decision run's output commit, whose
  row is pinned through the 3L verifier, plus SEC documents accepted ≤ T under the frozen acceptance rule, from the 3M
  store. Builder: v7 (`4bc9425`; AUDIT_N6 addendum: v6 failed the CROSS_CHECK_O 6a regression test); the version used is recorded per run
  and never mixed within one formation.
- **Model and prompt:** `rs2-analyst-deep-mtp5-v33`, prompt `m3m.prompt.v3`, contract `m3m.analysis.v2` (with the
  designator exemption), all seven tasks plus `material_events`, seed base 1000, one run per name. `thesis_change`
  runs with the name's prior formation run as its prior (§3P builds on this).
- **The 2026-09-30 formation** is analysed after the fact (its run passed the 3L verifier, so the regime is still
  `verified`). It is labelled `retrospective`: it measures what the model does with that evidence, not what the system
  held then, and its FQ/FB rows are reported apart from the contemporaneous ones.
- **The 2026-10-30 formation** (fill 2026-11-02) and later are contemporaneous: each analysis is complete, hashed and
  logged before the fill session opens, or the name is `analysis_pending`.

## 5. Shadow label for FQ and FB

SPEC_factor_led_v2 §4 disables a model-driven buy pause "until the event verification rate, false-positive cost,
maximum pause duration, expiry and independent review are registered and measured". Here:
- maximum pause and expiry are registered (§3.4);
- verification rate and false alarms are measured by 3N (DEV now, FRESH next);
- independent review is the 3N RR and its cross-check.

FB and FQ are measurement series. F (A0) stays the paper book of record until the operator adopts something else
(CROSS_CHECK_O 4). Until 3N closes, FQ and FB are labelled `shadow_pre_3N_close`. The series are computed the same way either way; the
label says that no rule had been validated when the action was recorded. After 3N closes, the label becomes
`paper_post_3N` from the next formation on. Old rows are never relabelled.

## 6. Records (`stocks-workspace/scratch/rev23/m3o/ledger/`, append-only, schema `m3o.decision.v1`)

| File | One line per | Holds |
|---|---|---|
| `formations.jsonl` | formation | T, run id, output commit, verifier verdict, A0 book (copied by reference from m3l_forward) |
| `factor.jsonl` | formation × name | band, door, rank, `fct_flags`, prior-book membership per arm |
| `qwen.jsonl` | formation × name | run id, manifest sha256, builder/prompt/contract versions, task statuses, analysis state |
| `verification.jsonl` | formation × name | B hits; every critical material_events claim with its support, status, `occurred_on`; Q1 verdict |
| `actions.jsonl` | formation × name × arm | action, rule id, reason, weight before (drifted) and target, label |
| `marks/<asof>.json` | mark | per arm: gross and net returns, turnover, costs, cash drag, drawdown, SPY |

Every line carries the engine version and sha256, the sha256 of the inputs it read, and (for Qwen-derived lines) the
qwen_c git commit from the run manifest and `builder_code` from the packet (CROSS_CHECK_O 8a). A recomputation that differs from a stored
line stops the engine (as forward_ledger.py does).

## 7. Measures (PLAN §3O item 9)

Per arm, per period and cumulative: gross and net returns (0/20/60 bp round trip), one-way turnover from drifted
pre-trade weights, cost drag, maximum drawdown, volatility, SPY excess.

- **Factor-adjusted performance:** reported as `not_estimable` until 12 monthly observations exist.
- **Event-response outcomes:** for each restriction, the restricted name's return over the restriction period against
  the arm's book (was it avoided loss or missed gain); for each name later found to have had a critical event
  (3P journal, 3N-style truth review), whether B or Q restricted it and when.
- **Qwen operations:** analyses per formation, completion rate, latency from T to completion, pending and incomplete
  counts, GPU hours.

## 8. Pass criteria mapping (PLAN §3O)

| PLAN criterion | Evidence |
|---|---|
| Qwen present in every completed formal deep analysis | every FQ entry has `analysis_state == complete` and a run id; no factor-only fill in FQ |
| Factor evidence, Qwen judgment, verification and action separately logged | the four files in §6, reconciled by an audit script |
| Entry/hold/review/exit rules preregistered and explainable | this SPEC and PREREG_m3o.json, frozen before the 10-30 formation's analyses |
| No look-ahead or undocumented omission | packet acceptance ≤ T; fill after T; every name in A0 appears in every arm's actions with a reason |
| Adoption requires independent evidence and approval | no arm is adopted in 3O; adoption is an operator decision after 3S |

## 9. Work orders

| WO | What | GPU | Order |
|---|---|---|---|
| WO_O1 | Paper decision engine (`m3o_engine.py`) with fixtures; no GPU, no network | no | now |
| WO_O2 | 2026-10-30 formation: verify run, build packets, Qwen analyses before the 11-02 open | yes, ~12 h | first decision run after 10-30 close |
| WO_O3 | 2026-09-30 formation, retrospective packets and analyses | yes, ~12 h | after 3N FRESH |
| ~~WO_O4~~ | ~~F-A1 forward book~~: withdrawn (CROSS_CHECK_O 5) | | |

GPU priority: the 3N DEV run first (running), then WO_O2 (time-critical: an unrecorded formation is lost forward
evidence), then 3N FRESH and the DEV regression rerun, then WO_O3.

## 10. Operator decisions

None blocks 3O. Reserved for later, unchanged: adopting any arm; a forced-exit policy; the allowable verified-action
list for real money; paper-to-real cutover.
