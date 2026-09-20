# Upstream handoff — RS2 → Depth migration (for the Stock Screener session)

**Date:** 2026-08-25
**Author:** RS2 Local (upstream / producer side)
**Purpose:** describe exactly what changed on the *producer* side so the downstream
(Stock Screener repo + website) can be migrated consistently. This document does **not**
change any downstream code — it is the spec the downstream fix should follow.

---

## 1. TL;DR

The old local-RS2 analysis pipeline was **retired by operator order on 2026-08-21** and replaced
by the **depth pipeline**. The producer now publishes a different file, with a **different schema**,
under a different scoring philosophy ("direction of an intrinsic-value *band*", not a point verdict
with a numeric conviction).

| | OLD (retired) | NEW (live) |
|---|---|---|
| Producer | `orchestrate.py` → `run_rs2.py` (local Ollama Qwen) | `orchestrate_depth.py` → `depth_pipeline.py`, **and** `api_llm/publish_cloud_verdicts.py` (cloud DeepSeek) |
| Published file | `public/data/llm_overlay.json` | `public/data/depth_overlay.json` (+ `public/data/depth_reports/{TICKER}.json`) |
| Schema id | RS2 verdict (`method: reverse_dcf`) | `scheme: band_direction_v1` |
| Core signal | `conviction` (numeric 4–14) + `action` free-text + `fair_value` point | `direction` (categorical) + `size_hint` (categorical) + IV **band** |
| Status | **frozen** since 2026-08-19 (producer paused forever) | **live**, refreshed continuously (last publish 2026-08-25 10:24Z, 165 names) |

**The old file is dead but still being consumed downstream.** `llm_overlay.json` last regenerated
2026-08-19; it will never update again (the old orchestrator is held down permanently by
`cache/PAUSED`, exits 0 without publishing by design). Anything still reading it is reading a
frozen snapshot. That is the whole reason for this migration.

---

## 2. What the OLD pipeline did (so you know what to unwire)

- `orchestrate.py` aggregated every ACTIVE RS2 verdict into `llm_overlay.json` and pushed it to the
  screener repo (Vercel auto-redeploys).
- Downstream, `scripts/score_factors.py::apply_llm_overlay()` read that file and wrote the
  `fct_*_llm` family onto `factor_scores.json`:
  `fct_band_llm`, `fct_percentile_llm`, `fct_llm`, `fct_llm_veto`, `fct_llm_verdict`,
  plus the parallel `fct_stance` / `fct_band_llm_score`.
- Those fields fed: the LLM portfolio A/B (`build_portfolio_plan.py --llm` →
  `portfolio_plan_llm.json`), the paper-portfolio sleeves (`track_paper_portfolios.py`:
  `plan_llm` / `plan2_llm` / `equal_llm`), and the site ranking desk (`lib/desk/rankings.ts`).

**Retirement is intentional and permanent.** Do not "fix" the freshness by restarting the old
orchestrator — it was dropped on purpose. The fix is to migrate consumers onto the depth data.

---

## 3. What the NEW pipeline publishes

Two producer arms, **identical output schema**, both push to the same place:

1. **Local arm** — `orchestrate_depth.py` (Ollama `rs2-analyst-deep`).
2. **Cloud arm** — `api_llm/publish_cloud_verdicts.py --push` (DeepSeek `deepseek-v4-flash`).
   It *imports* `orchestrate_depth.rebuild_overlay()` / `publish_overlay()` — same code path, so
   the file it produces is byte-compatible with the local arm's. Verdicts carry an `arm` field for
   provenance; downstream can ignore which arm produced a row.

**Cloud verdicts are production-effective, not experimental.** Operator decision 2026-08-25
(option A): cloud (DeepSeek v4 flash) verdicts join the **same** ledger and the **same**
`depth_overlay.json` as local ones, stamped with provenance, pushed by the same path — approved on
a 28-ticker A/B where flash agreed with the local Qwen. They are authoritative, and they are now the
**dominant** source: in the current live overlay, **131 of 165 rows (79%) are cloud
(`deepseek-v4-flash`)**, 34 are local (`rs2-analyst-deep` / `-mtp5`). Downstream must treat every
row as equally valid regardless of `model` / `arm` — **do not filter, gate, down-weight, or
special-case cloud rows.** `arm` and `model` are provenance/telemetry only; the verdict contract
(`direction`, `size_hint`, IV band, `mos_vs_median_pct`) is identical across arms.

Both arms:
- append the verdict to an append-only ledger (upstream-only: `cache/depth_ledger.jsonl`),
- rebuild the **newest-verdict-per-ticker** view into `public/data/depth_overlay.json`,
- write a per-ticker prose bundle into `public/data/depth_reports/{TICKER}.json`
  (verdict + the 3 sample reports, for the site's depth panel),
- commit + push to the screener repo.

**Downstream reads only these two paths.** The ledger stays upstream.

---

## 4. NEW schema — `public/data/depth_overlay.json`

Top level: `{ generated_at, scheme: "band_direction_v1", count, tickers: { TICKER: {...} } }`

Per-ticker fields:

| field | type | meaning |
|---|---|---|
| `ticker` | str | symbol |
| `price` | float | price at analysis time |
| `date` | str `YYYY-MM-DD` | verdict date |
| `model` | str | `rs2-analyst-deep` (local) or `deepseek-v4-flash` (cloud) |
| `samples_run` | int | samples attempted (typically 3) |
| `n_basis` | int | usable+complete samples the verdict rests on (0–3) |
| `iv_band_low` | float | **lowest** plausible intrinsic value across samples |
| `iv_band_high` | float | **highest** plausible intrinsic value across samples |
| `median_iv` | float | median intrinsic value across samples |
| `spread_pct` | float | dispersion of the IV band (band width as %); **confidence proxy — smaller = more agreement** |
| `direction` | enum | `undervalued` \| `overvalued` \| `hold` \| `NOT_USABLE` |
| `size_hint` | enum\|null | `full` \| `half` \| `quarter` \| `null` |
| `mos_vs_median_pct` | float\|null | `(median_iv / price − 1) × 100`; **+ = upside/undervalued, − = overvalued** |
| `consensus_dir` | str | upstream run-dir id (matches `depth_reports/{T}.json` run) |
| `flags` | list[str] | integrity/threshold annotations; informational, gate nothing |
| `arm` | str | `cloud_api` or absent (local) — provenance only |
| `backfilled` | bool | present on backfilled rows only |

Ledger-only fields that may leak into a row but are **not** part of the consumer contract:
`pack_revision`, `pack_source`, `research_brief_age_days`, `searxng_up`, `published_by`,
`published_at`, `rederived_at`, `supersedes`, `reason`. Treat as opaque.

---

## 5. Derivation rules (so downstream mapping is principled, not guessed)

From `depth_pipeline.py::band_verdict`:

**direction** — price vs the *band edges* (not the median):
- `overvalued` if `price > iv_band_high` (every plausible draw values it below price)
- `undervalued` if `price < iv_band_low` (every plausible draw values it above price)
- `hold` if `iv_band_low ≤ price ≤ iv_band_high` (price inside the model's honest uncertainty — no edge)
- `NOT_USABLE` if zero plausible complete samples (malfunction, **not a verdict** — skip it)

**size_hint** — from `spread_pct` via `SIZE_BUCKETS = ((15.0,"full"),(30.0,"half"),(inf,"quarter"))`:
- `spread_pct ≤ 15%` → `full`
- `spread_pct ≤ 30%` → `half`
- else → `quarter`
- Special case: a **single-sample basis** (`n_basis == 1`) is forced to `quarter` regardless of spread.

`size_hint` is a **conviction/agreement proxy**, not a target weight. It says how tightly the
samples agreed, gated to a coarse sizing bucket. There is **no numeric conviction and no
recommended-weight percentage** in this scheme.

**Important:** `direction` uses band edges; `mos_vs_median_pct` uses the median. They can disagree
in sign — e.g. `direction=hold` (price inside the band) with a negative `mos_vs_median_pct` (price
above the median but below `iv_band_high`). Do **not** derive direction from the sign of
`mos_vs_median_pct`.

---

## 6. Old → New field mapping (the crux)

| OLD `llm_overlay` field | NEW equivalent | notes |
|---|---|---|
| `stance` (undervalued/fair/overvalued) | `direction` | **middle value is `hold`, not `fair`** |
| `fair_value` (point) | `median_iv` (+ band `iv_band_low`/`high`) | new gives a band, not a point |
| `mos_pct` / `realistic_mos_pct` | `mos_vs_median_pct` | **same formula & sign convention**, computed vs `median_iv` |
| `consensus_median` (sell-side target) | — | **no equivalent**; `median_iv` is the model's own IV, a different quantity |
| `conviction` (numeric 4–14) | `size_hint` (full/half/quarter) + `spread_pct` | **NO numeric conviction** — categorical proxy only |
| `recommended_weight_pct` (numeric %) | `size_hint` (categorical) | **NO numeric weight** |
| `action` (free-text; BEAR/BULL/HARD_SELL keyword scans) | `direction` | categorical; there is no free-text action to keyword-scan |
| `entry_timing` / `pullback_trigger` | — | **no equivalent** |
| `stance_score` / `thesis_break` | — | **no equivalent** |
| `expectations_gap_pts` / `brake_applied` / `band_at_analysis` | — | **no equivalent** |
| `method` (`reverse_dcf`) | `scheme` (`band_direction_v1`) | different id; consensus-of-samples, not one reverse-DCF |
| `analyzed_date` | `date` | rename |
| `report` (single dir id) | `consensus_dir` (+ `depth_reports/{T}.json` bundle) | prose now shipped as a bundle |

### The gaps that need a downstream/operator decision (STOP points)

These OLD inputs have **no depth equivalent**. Any consumer that relied on them must be redesigned,
not silently repointed. Do not fabricate a numeric conviction/weight from `size_hint` without an
explicit, ratified mapping:

1. **Numeric conviction gates.** `score_factors.apply_llm_overlay` bands on `conviction ≥ 9.5`
   (research_now) / `≥ 8.0` (watchlist). Depth has no such number. New band logic must be defined
   from `direction` + `size_hint` (+ optionally `mos_vs_median_pct`, `spread_pct`).
2. **Conviction-weighted sizing.** `build_portfolio_plan.py --llm` and the paper sleeves size from
   `fct_llm_verdict.conviction`. Depth gives a bucket (`full`/`half`/`quarter`), not a number.
   Someone must decide the bucket→weight rule (or drop LLM-driven sizing and equal-weight it).
3. **The `llm_reject` veto.** OLD set `fct_llm_veto = "llm_reject"` on hard AVOID/SELL. Depth's
   analog is `direction == "overvalued"` — but decide whether *every* overvalued name is a hard
   reject, or only e.g. `overvalued` with `mos_vs_median_pct` below some threshold.
4. **entry_timing / pullback_trigger.** Consumed by the F-04 hysteresis in
   `track_paper_portfolios.py` and shown in UI. No depth source. Decide: drop, or re-derive a
   hysteresis from the band (e.g. exit only when price clears `iv_band_high` by a margin).

### Recommended band-gate mapping (measured 2026-08-25; thresholds pending operator ratification)

> **Correction:** an earlier draft of this doc called `size_hint` "the conviction axis." Measurement
> below shows `size_hint` is band-width / sample-agreement and is roughly **independent of
> `direction`** (overvalued names are `full` too). It is therefore *not* a directional-confidence
> signal and should be used as a **reliability floor**, not as the research_now/watchlist
> discriminator. Reading band width as conviction is the kind of weaker-method substitution the
> project standard forbids.

Measured on the 165 live rows:
- `direction × size_hint`: undervalued {full 9, half 8, quarter 7} = 24 · hold {full 4, half 7,
  quarter 33} = 44 · overvalued {full 16, half 20, quarter 61} = 97.
- Among the 24 `undervalued`: `mos_vs_median_pct` median 17.1%, **15 ≥ 15%, 9 ≥ 30%**.

**Axes:**
- **Edge / membership → `direction`.** Only `undervalued` (price below the *entire* IV band) is
  eligible for research_now / watchlist. `hold` (price inside band = no edge) → monitor.
  `overvalued` → demoted. `NOT_USABLE` / `size_hint == null` / missing row → silence (no verdict;
  never fall back to the quant band).
- **Reliability floor → `size_hint`.** `quarter` (spread > 30% or a single-sample basis) = low
  agreement → **cap at watchlist**, never research_now. A wide-band, low-agreement name should not
  sit at top conviction in a real-money book. Floor only, not the RN/WL discriminator (see
  correction above).
- **Magnitude → `mos_vs_median_pct`.** Discriminates RN (deep) from WL (shallow). `undervalued`
  already guarantees a positive floor; `mos` sizes how deep.

**Rule — STRICT default (recommended for the A/B start):**
- **research_now** = `direction == undervalued` AND `size_hint ∈ {full, half}` AND
  `mos_vs_median_pct ≥ 30` → **6 names** measured (full 3 + half 3).
- **watchlist** = `direction == undervalued` AND not research_now (full/half with `15 ≤ mos < 30`,
  plus all quarter-undervalued as reliability-capped) → **~18 names**.
- **monitor** = `direction == hold`. **demoted** = `direction == overvalued`. **none** =
  NOT_USABLE / missing.

**Looser variant** if 6 RN names is too thin: drop the RN gate to `mos ≥ 15` → **10 RN names**
(full/half, mos ≥ 15). Start STRICT and loosen only if the book is too small — this governs a real
paper-money A/B.

**Operator must ratify each — do not ship without a call:**
1. **`size_hint` as reliability floor vs conviction axis.** This proposal uses it as a floor (cap
   `quarter` at watchlist). If you want conviction-graded bands, depth carries **no conviction
   number** — it must be emitted upstream, not synthesized from band width.
2. **`entry_timing == buy`** (old alternate RN trigger) has **no depth analog** — dropped. RN is now
   purely direction + mos + reliability.
3. **`hold` + deep mos.** 7 names (HRMY +30.9%, GMED +27.2%, HG +25.4%, SENEB, CAAP, FLXS, M) sit
   below their `median_iv` but *inside* the band, so depth rates them `hold` (no edge). The old
   deep-MoS bypass would have promoted the ≥30 ones. **Recommendation: honor depth** — a band that
   straddles price is genuine uncertainty; resurrecting them via a median-only bypass reintroduces
   the point estimate the band scheme was built to reject. Behavior change vs old; operator's call.
4. **Thresholds (30 / 15, cap-quarter)** mirror the old MoS gates; they are not independently
   calibrated. Ratify against desired book size and risk tolerance.

---

## 7. Known downstream touchpoints (found via targeted grep — NOT a guaranteed-complete sweep)

The downstream session should re-run the sweep to confirm completeness. Files that currently read
the OLD overlay / `fct_*_llm`:

- `scripts/score_factors.py` — `apply_llm_overlay()` reads `public/data/llm_overlay.json`, writes
  `fct_band_llm` / `fct_percentile_llm` / `fct_llm` / `fct_llm_veto` / `fct_llm_verdict` /
  `fct_stance` / `fct_band_llm_score`. **This is the root; migrate it first.** While it keeps
  reading the frozen file it re-applies a stale Aug-19 snapshot on every scoring run (stale-decay
  only halves conviction once past 14 days; `llm_reject` vetoes are staleness-immune and persist
  forever).
- `scripts/build_portfolio_plan.py` — `--llm` variant → `portfolio_plan_llm.json`
  (`fct_band_llm`, `fct_llm_veto`, `fct_llm_verdict.conviction`).
- `scripts/track_paper_portfolios.py` — `plan_llm` / `plan2_llm` / `equal_llm` sleeves; also reads
  `llm_overlay.json` directly for the F-04 hysteresis (`fair_value`/`mos`).
- `lib/desk/rankings.ts` — reads `fct_percentile_llm` / `fct_llm_veto` (already derives promo/demote
  from the depth verdict and notes `fct_llm` is "retired" — partial migration already started).
- `lib/data-service.ts` — types + `fetchDepthOverlay()` (`/data/depth_overlay.json`) already exists;
  `DepthOverlayPayload` is defined. Depth read path is already partly wired on the site.
- `.github/workflows/overlay-freshness-watchdog.yml` — watches `llm_overlay.json` `generated_at`
  (>36h alert). **Repoint at `depth_overlay.json` or it alerts on the dead file forever.**
  Also folded into `.github/workflows/price-refresh.yml` (same check) — repoint both.
- `scripts/tradability.py` — appeared in the `llm_overlay` grep; verify its use.

Suggested sweep to confirm completeness (run in the screener repo, exclude `public/data` and
`node_modules`):

```
rg -n 'llm_overlay|fct_band_llm|fct_percentile_llm|fct_llm|fct_stance|fct_band_llm_score|portfolio_plan_llm|equal_llm|plan_llm'
```

---

## 8. Gotchas / consistency traps

- **`generated_at` format differs — downstream owns the parse.** OLD used ISO with a `Z` suffix
  (UTC). NEW `depth_overlay.json` uses `datetime.now().isoformat()` — **no `Z`, naive local time.**
  **The upstream stamp stays as-is; it will not change.** So any consumer that reads
  `depth_overlay.json`'s `generated_at` must parse a naive-local ISO timestamp — do **not** apply the
  old `ts.replace("Z","+00:00")` trick, which yields a naive datetime and makes a
  `now(tz=utc) − dt` subtraction raise. Concretely, when you repoint the freshness watchdog
  (`overlay-freshness-watchdog.yml` + the folded copy in `price-refresh.yml`) at the depth file,
  replace its parse with a naive-local read (`datetime.fromisoformat(ts)` compared against
  `datetime.now()`), not the UTC path.
- **Middle stance renamed.** OLD `stance == "fair"` → NEW `direction == "hold"`. Any equality check
  on `"fair"` silently stops matching.
- **`NOT_USABLE` / `size_hint == null`** = no verdict. Mirror the OLD `evaluated_llm()` guard:
  a missing/`NOT_USABLE` row must read as silence, never fall back to the quant band (that bug
  manufactured phantom departures in the paper sleeves — 19 on 2026-06-30, 57 on 2026-07-05).
- **Count drift is expected.** OLD had 172 names, NEW has 165 — different universe timing, not data
  loss.
- **Do not filter by `model` / `arm`.** Cloud (`deepseek-v4-flash`) rows are production-effective
  and currently 79% of the book (see §3). Any code that keys on model name, or that assumes rows are
  local-Qwen, will drop most of the live overlay.
- **Do not restart the old orchestrator.** `cache/PAUSED` is deliberate and permanent.

---

## 9. Open question back to upstream — conviction is MISSING, not "expressed differently"

**Do not treat sample-agreement as conviction. They are orthogonal.**
- **Sample agreement** (`spread_pct` / `size_hint`, `converged`) = reliability of the IV *number* —
  estimator variance across repeated runs of the same model.
- **Conviction** = the intelligence's judgment about the *security itself* — thesis strength,
  durability, payoff asymmetry. A first-order signal about the stock.

High agreement on a weak stock, or high conviction on a noisy IV, are both normal — the two do not
track each other. The depth redesign **dropped** the analyst's conviction score and kept only a
sampled IV; it did **not** substitute one for the other. Note also that `mos_vs_median_pct` is not
conviction: a large discount can be a value trap. So the depth bands, as they stand, gate on
**direction + cheapness with no conviction input** — they cannot separate cheap-and-strong from
cheap-and-broken. **For a real-money A/B this is a material regression from the old book, not a
formatting difference.** Whoever surfaces the depth bands should state this limitation until it is
fixed.

**Correct fix (producer-side, additive) — restore conviction as a *sampled scored quantity*,
exactly parallel to IV:**
1. the depth prompt asks each sample for a **conviction score** on its call;
2. `consensus_valuation.py` aggregates **conviction median + spread** alongside the IV median +
   spread (two sampled quantities, so conviction gets the same N-sample reliability treatment as
   IV);
3. the verdict / overlay carries `conviction` (+ its own agreement), so the §6 band gate can use a
   real conviction axis again.

This touches the depth prompt and consensus aggregation (**the engine** — additive change, operator
sign-off required). Until it lands, the §6 mapping runs on direction + MoS + a reliability floor
only, with **no conviction axis**.

The other missing quantities (recommended weight, entry trigger) are likewise producer-side: add
them at the source if needed, do not approximate them downstream from `size_hint`.
