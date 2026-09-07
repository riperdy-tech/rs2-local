# Depth Orchestrator — Run Criteria & Cadence (spec of record)

**Date:** 2026-08-25. **Author decision:** operator (riperdy) + analysis this session.
**Status:** accepted. Event-driven core is LIVE; the boundary/dwell additions (#5, #7, retire,
held-exempt) are wired additively and warm up over 5–15 days as membership history accrues.

This file is the single record of *when the local depth tier re-analyses a name*. It supersedes
the old timer-based cadence (`orchestrate.py`'s 7-day RN / 14-day watchlist refresh), which was
retired because it re-ran the whole book on a clock and cannot survive the depth tier's
~1.5h-per-name cost.

---

## 0. Why the old cadence was dropped

The retired pipeline (`orchestrate.py`) refreshed every research_now name every 7 days and every
watchlist name every 14, on the calendar, regardless of whether anything changed. At depth cost
that is ~16 forced runs/day before any events — permanently behind. The depth tier instead
re-runs **on events**, not on a timer, with a 90-day rotation as the only staleness floor.

---

## 1. Measured facts this rests on (all from this repo, 2026-08-25)

- **Per-name wall time:** median **1.3h**, mean **1.9h** (23 runs, `cache/depth_orchestrate.log`).
- **Machine capacity:** ~**13 names/day** at 24/7; ~**11.6/day (81/week)** at 21h/day (an
  8–11pm downtime break).
- **Live book:** 170 names (research_now 51 + watchlist 119, `factor_scores.json`).
- **Steady demand (deduped union of all triggers):** mean **43/week**, peak (earnings) **112/week**.
- **Peak week lag at 81/week capacity:** ~**1.7 days**, and only **1 week/year** shows any backlog.
- **Verdict direction split (165 live):** overvalued **59%**, hold **27%**, undervalued **15%**.
- **Quant composite weighting** (what RN membership rewards): revisions 0.173, momentum 0.096,
  lowvol 0.086, value 0.066, quality 0.062. **Value is nearly the smallest weight** — quant RN and
  our intrinsic-value verdict measure *different things*. This is why a quant exit is NOT
  confirmation our thesis broke, and why favorable-verdict exits get a diligence re-run (§3).
- **Band round-trip curve** (327 out-and-back spells): median out-spell **2d**, p75 **5d**,
  p90 **13d**. Sets the dwell constants in §4.

---

## 2. Machine rhythm

- Run **continuous, ~21h/day** (operator's 8–11pm break). The orchestrator stops at a **ticker
  boundary** (finishes the current name, never mid-run) when it sees `cache/DEPTH_PAUSED`.
- **One** depth child at a time; per-name watchdog with tree-kill + VRAM unload; MAX_RETRIES=2.
- **Daily 08:00 free pass (no model):** price-vs-band direction on all 170 + rebuild the trigger
  map + publish `depth_overlay.json`. Minutes, not hours. This is the "daily orchestrator run."
- The model sweep runs off the trigger queue whenever capacity is free.

---

## 3. Run criteria — the complete list

### Name WITH a verdict — re-runs if ANY is true

| # | trigger | detail | status |
|---|---------|--------|--------|
| 1 | **8-K** | an 8-K filed after the verdict date (news: guidance, M&A, buybacks, exec exits) | LIVE |
| 2 | **earnings filing** | 10-Q / 10-K / 20-F / 40-F filed after the verdict, *once our own fundamentals tables reflect it* (else `filing_pending`, deferred) | LIVE |
| 3 | **price move** | today's price is **>8%** from the price the verdict was struck at | LIVE |
| 4 | **pack revision** | the data pack gained data or corrected a declaration since the verdict | LIVE |
| 5 | **persistent re-entry / RN-promotion** | name crossed back into RN+WL and stayed (entry dwell, §4), AND its verdict is older than the freshness bar | NEW — warms up |
| 6 | **90-day rotation** | verdict older than `depth_rotation_days` (90). Staleness floor; runs only when no triggered work remains | LIVE |
| 7 | **exit-review** | name LEFT RN+WL and stayed out ≥ exit-review dwell (§4), AND (verdict = **undervalued** OR name is **held**). One diligence re-run before any disposition | NEW — warms up |

### Name WITHOUT a verdict

| 8 | **new-entrant baseline** | in RN+WL and past the **5-day entry dwell**; queued ahead of rotation, behind triggered work | LIVE (dwell is NEW) |

### Book membership & retirement

| 9 | **retire** | name out of RN+WL ≥ **15 days**, **not held**, verdict neutral/negative → drop from the active book (stop the daily filing/price checks). Old verdict stays in the ledger as record; a later return is re-analysed fresh as baseline. **Retire ≠ sell** — it is a *compute-coverage* decision, no position is touched. | NEW — cannot fire for 15d |
| 10 | **held-exempt** | any name in `paper_ledgers` `state.holdings` (union across scopes) is **never retired** and is always analysed, whatever quant does. A held name quant drops gets the §3 exit-review, never silence. | NEW |

---

## 4. Hysteresis constants (from the round-trip curve, §1)

| constant | value | basis |
|----------|-------|-------|
| **Entry dwell** (IN before we analyse) | **5 trading days** | round-trip median 2–3d; 5d clears the straddle-flicker |
| **Exit-review dwell** (OUT before diligence re-run; favorable/held) | **3 trading days** | eager — protects the 15% of buys; cheap (~3–4/wk) |
| **Retire dwell** (OUT before dropping coverage; neutral/negative, unheld) | **15 trading days** | p90 of returns = 13d → at 15d only ~9% ever round-trip back |
| **Post-run cooldown** (refractory after any re-run) | **7 days** | damps the earnings cluster (one event = one run, not four). *Reasoned, not fitted.* |
| **Freshness bar** (re-entry #5 re-runs only if verdict older than this) | **21 days** | default; the one constant still un-fitted. Only affects how eagerly re-entries re-run. |

**Asymmetry is deliberate, on two axes:**
- *Direction:* favorable/held names get a diligence re-run on exit; the 85% neutral/negative retire cheaply.
- *Speed:* re-check favorable exits fast (3d, before we lose sight); retire the rest slow (15d,
  because losing coverage is worse than a wasted refresh).

---

## 5. Priority order (when the queue exceeds capacity)

1. Event-triggered (8-K / filing / move) **+ exit-review**
2. Baseline (never analysed)
3. Re-entry / promotion
4. Rotation (staleness floor)

Within each class: research_now → watchlist → rest, then alphabetical.

---

## 6. Load vs capacity

| | runs/week |
|---|---|
| Capacity (21h/day) | ~81 |
| Demand, average week | ~43 (53% load) |
| Boundary rules net add | +2 to +6 (roughly cancelled by retires) |
| Peak earnings week | ~112 → ~1.7-day lag, 1 week/year |

Capacity is not the binding constraint; the single peak earnings week is, and it is tolerable.
The cloud DeepSeek-V4-flash arm was used ONCE to fill the initial baseline (165/170) and was
**parked** as of this date — not part of the steady cadence, optional pressure-relief for the
peak week. **Amended 2026-09-07 (§8):** it is now the *continuity arm* — it serves this same queue
while the PC is off. It still adds no capacity while the PC is on.

---

## 7. Open items / not yet fitted

1. **Freshness bar (21d)** is the one constant on a reasoned default, not a measured fit. Safe to
   ship; tune once re-entry history exists.
2. **8%-move rate** (~10/wk) in the load model is an estimate; the trigger itself is measured to
   fire on a fresh price source. Pin it by replaying full daily prices vs verdict prices if the
   load headroom ever tightens.
3. **Warm-up:** #5/#7/#9 depend on the daily membership snapshot (`cache/depth_membership.jsonl`),
   which begins accumulating on the first scheduled run. They are dormant until 5/3/15 days of
   history exist. Retire (#9) is destructive and must be operator-reviewed before it is un-gated;
   it cannot fire for 15 days regardless.

---

## 8. Continuity arm (amendment, 2026-09-07)

**Operator decision:** "I want DeepSeek AI to run the sweeps (the homework, per agreed schedule)
even though my PC is off, so it ensures continuity." Measured cause: the PC was off 2026-09-02 →
09-06, the cadence's trigger queue went unserved, and the old cloud backstop
(`depth-cloud-backstop.yml`) instead ran an *oldest-verdict-first* sweep of never-analysed names —
not this spec's queue, not its priority order, and without the entry dwell (#8).

**Rule: the cloud serves THE SAME QUEUE.** §3 run criteria and §5 priority live in one pure
function, `orchestrate_depth.build_queue()`, called by the PC sweep and by the cloud driver
(`api_llm/cloud_backstop.py`) on the same inputs (ledger, `depth_state.json`, trigger map,
membership log, held names, `factor_scores.json`). Nothing in this spec's *when* or *in what
order* differs between the arms. What differs is *who* analyses and *how well*:

| | PC arm (primary) | cloud continuity arm |
|---|---|---|
| runs when | PC on; RS2-Depth-Orchestrator every 4h | PC heartbeat dead >90 min; GitHub cron ladder 10:05/14:05/18:05/22:05 UTC (same 4h rhythm) |
| model | local `rs2-analyst-deep-mtp5` (Ollama) | DeepSeek-V4-flash, **off-peak only** (`api_llm/deepseek_offpeak.py`; Mon–Fri 01–04 / 06–10 UTC never runs, `force` cannot override) |
| queue | `build_queue()` | `build_queue()` — identical, first `BACKSTOP_MAX_TICKERS` (6) per run |
| research | local brief + SearXNG + sec_facts | no local brief, CI SearXNG best-effort, no sec_facts (degraded by design) |
| verdict stamp | `arm` absent (local) | `arm: cloud_api`, `published_by: publish_cloud_verdicts.py` |
| local-verdict protection | n/a | **lifted** (`--allow-local-overwrite`): a trigger on a locally-analysed name is served, not left waiting. The local arm re-takes the name on its next trigger. Manual cloud publishes keep the protection. |
| membership snapshot | one row per sweep-day | one row per sweep-day (same clock, `TZ=Asia/Taipei`) — the dwell clocks (§4) keep advancing |
| state | `cache/` | seeded from `rs2-state`, handed back after each run: ledger delta (append), `depth_membership.jsonl`, `depth_state.json` (incl. the shared retry budget) |

**Hand-back and merge (PC return).** `sync_state.py` imports the ledger delta (dedupe-append),
merges membership rows by date (local row wins on the same date), and takes `depth_state.json`
rows only where the cloud stamped them (`arm: cloud_api`) *and* they are newer than the local row.
Nothing the PC recorded is ever overwritten by the cloud copy.

**Interlocks unchanged:** ledger-seed non-empty, backup-rot check (last PC sync vs last heartbeat
≤2h), overlay-count guard (rebuilt ≥ published), publish-time PC-alive re-check, fail-closed on an
unreadable heartbeat. The old *overlay >30h stale* gate is removed: continuity means every missed
4h tick is served, not only after the overlay has rotted.

**What this does NOT change:** the PC is primary; the cloud runs zero names while the heartbeat is
live. Rule #8 entry dwell is now enforced in `build_queue()` for both arms (this spec has listed it
LIVE since 08-25; the PC code did not gate on it before this change — measured 2026-09-07: four
one-day entrants ADI/BRC/HNGE/OKTA that the old code would have run are now held for the dwell).

