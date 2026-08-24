# P — LATENT MISALIGNMENT SWEEP OF THE VALUATION SYSTEM (2026-08-24)

Operator brief (Q2): *"do a sweep of our valuation system (including our checking and validation
logic, if any) to ensure no other dormant or latent mis-alignments exist that would harm or
otherwise distort our findings."*

Q1's answer is `N_guard_redesign_study_20260824.md`. This is Q2. Both are now applied; the
disposition of every finding is recorded below.

**Conclusion up front: the dominant failure mode is not broken code, it is TRUE STATEMENTS THAT
STOPPED BEING TRUE.** Four of the five findings are cases where a check or a declaration was
correct when written, kept running without error, and quietly went out of agreement with the
system it described. None of them raised anything. Every one reached a published verdict.

---

## 1. The pack declared that data it holds does not exist

The screener's extractor was rebuilt on **2026-08-23** and began filing stock-based compensation,
the debt components and the investment lines. `build_pack` neither printed those columns nor
noticed it now held them, so SECTION 12 went on declaring them "NOT EXTRACTED" and SECTION 2 went
on stating "we hold no per-year SBC series at all". Measured across the 171-name book, those
statements were **false on 164 names for SBC, 167 for the debt components, 100 for investments**.

Not cosmetic. On the newest fiscal year of each book name, SBC runs a **median 8% of operating
cash flow** (p75 20%, max 183%) — an owner-earnings figure built from OCF without subtracting it
is overstated by that much. The unmapped debt components run a **median 30% of long-term debt**
(p75 66%). Investments run a **median 32% of the cash balance** (p75 93%), which is enough to flip
the SIGN of net debt — the exact failure SECTION 12 warned about, while the data sat unread in the
record it was warning us about.

**Fixed** (`ab5e4c3`): SECTION 5 gains the filed SBC column; a new SECTION 6B prints the debt and
investment components; SECTION 12's affected lines are computed per ticker by `_decl()` from that
company's own record, so they cannot drift out of agreement with the tables again.

**No total debt is computed, deliberately.** The components measurably overlap and we cannot
resolve how: `lt_debt` and `debt_lt_noncurrent` are identical on 72 of the 80 book names carrying
both and disagree on 8 — Marriott by a factor of 650 ($0.023B against $14.995B) — and
`debt_current` and `short_term_borrowings_separate` agree on only 10 of 35. Which XBRL tag
produced each number is not recorded, so summing would double-count on most names and picking one
per company is a judgment. The pack states the disagreement and hands the choice to the model.

MAR shows the cost of the old presentation: SECTION 6's long-term debt column read `not available`
for 2014–2018 and $0.092B–$0.247B thereafter, for a company whose noncurrent long-term debt column
shows $9–10B and whose vendor scalar says $17.083B.

## 2. Schema drift was only ever watched in one direction

`_schema_drift` reported keys that **disappeared** from a source. Nothing watched for keys that
**appeared**, and nothing watched `fundamentals_history` at all — `EXPECTED_KEYS` covers the vendor
and enrichment records, not the filed series the valuation actually rests on. So when the extractor
rebuild added six fields, nothing was missing, the sensor stayed silent, and finding 1 above ran
undetected for a day and 30 verdicts.

An appearing field is the **more dangerous** direction. A vanishing one breaks something visibly;
an appearing one leaves the pack working perfectly while a statement inside it becomes false.

**Fixed** (`5e3a77f`): `_unreviewed_history_fields` compares each year row against
`REVIEWED_HISTORY_KEYS`, an explicit list of the 33 keys we have actually looked at. Anything
outside it raises a block in SECTION 12 telling the model the tables are incomplete by exactly
that much and that the "we do not hold it" lines may be stale. Verified silent across all 5,603
screener tickers now that the new fields are reviewed, and verified to fire on an injected field.

## 3. Provable 1000× filed-series corruption reached a published verdict

`data_health` has known since 2026-08-08 that the SEC corpus contains periods recorded a clean
factor of 1000 from the rest of their own series. The gate built around it exits non-zero only
when such a value reaches a live `base_cf`. **The depth pipeline computes no `base_cf`, and
`orchestrate_depth` never called the gate at all** — so the check was asking a question about a
pipeline that no longer publishes, while the pack printed the entire year series to the model as
filed fact.

The gate reports **CLEAR** today and clears all 12 known breaks. Three are inside the book, and one
had already reached a published verdict: **INCY's HOLD was produced from a pack stating $19.094B
of long-term debt for FY2018, a 1000× corruption of roughly $19M**, with nothing to indicate it.

**Fixed** (`bdb0c02`): `build_pack` runs `data_health.audit_series_breaks` for its own ticker and,
when it fires, leads the pack with an integrity alert naming the field and both years. The cells
are still printed unchanged — silently patching filed data would hide the defect instead of
disclosing it. `orchestrate_depth` gains a startup scan over the book and the whole series rather
than one derived quantity; it warns and does not block, because the affected packs now carry the
alert and three bad cells are not a reason to refuse to analyse 171 companies.

## 4. Aggregator sections implied a currency they did not have

SECTION 8 and SECTION 9 were labelled `[Aggregator]` with no date, so an analyst price target
fetched a month ago read exactly like one fetched this morning. Measured across the book: the
enrich and openbb records are a **median 8 days old, p90 13, max 32**, and 6 names have no record
at all. Targets, short interest and the trailing multiples all move inside that window.

**Fixed** (`d8cbd21`): `_age()` reads each record's own `_fetched_at` stamp — which both sources
already carry — rather than file mtime, which a no-op rewrite would falsely freshen. Records past
14 days are marked "STALE, discount accordingly"; a record with no stamp says so. On the book today
that marks 13 packs stale and 6 age-unknown. The depth pipeline does not refresh these sources, so
stating the age is the honest fix rather than implying currency.

## 5. Nothing tied a verdict to the pack revision that produced it

A verdict is only as good as the facts the model was shown, and findings 1–4 change those facts.
Without a link, the book would end up half-analysed on each pack — the same two-regimes problem the
Q1 re-derivation was done to avoid, except **this one cannot be fixed retroactively**: re-deriving
needs the model to see the corrected facts, which means a re-run.

**Fixed** (`efd2bfc`): `PACK_REVISION` in `capability_test`, bumped only when a change alters what
the model is told — not for wording, since each bump re-runs the published book at roughly 76
GPU-minutes a name. `consensus_valuation` stamps it into `consensus.json`, `band_verdict` copies it
onto the verdict, and `depth_triggers` fires a `pack` trigger for any verdict below the current
revision. An unstamped verdict counts as revision 1, which is what makes the existing 30 eligible.
Ranked with rotation rather than with events, so the priority contract holds: verified against the
live queue, the 141 baseline names occupy positions 0–140 and all 30 re-runs sit at 141–170. The
book completes before anything is re-run, and no manual list has to be maintained.

---

## What this sweep did NOT find

- No arithmetic error in the band-direction verdict rule, the spread computation or the size
  mapping. Re-derivation of all 29 published verdicts under the corrected guard changed **0**
  directions, which is independent evidence the verdict logic is stable.
- No further false population counts beyond those in finding 1. The remaining hard-coded counts in
  SECTION 6 and SECTION 12 (33 unmapped debt tags, 18 non-diluted share tags, 51 capex-definition
  disagreements, 38 domestic-only pretax tags, 3,380,466 dimensionless fact rows) were **not**
  re-measured in this pass and remain unverified literals of the same class as finding 1. They
  describe defects rather than denying data, so a stale count misstates a magnitude rather than
  hiding a series — lower severity, but the same failure mode. **Open.**

## Open, and deliberately deferred

- **`SIZE_BUCKETS`** (15%/30% → full/half/quarter) was set before any spread data existed. Median
  observed spread is 45%, so almost everything lands in "quarter". Re-derive from the full 171-name
  distribution once the sweep completes — not from the 29 measured so far.
- **Re-measuring the five hard-coded population counts** above, and converting them to computed
  values the way `_decl()` now computes the SECTION 12 lines.
- **Refreshing** `enrich/` and `cache/openbb_` inside the depth pipeline, rather than only stating
  their age. Deferred: it adds a network dependency per ticker to a sweep that currently has none.
