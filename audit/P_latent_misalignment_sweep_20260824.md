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

## 6. The 8-K and filing triggers had never fired, once

Found on 2026-08-25 while investigating finding 7. `cik_map.json` is
`{"fetched_at": ..., "map": {TICKER: CIK}}`, and `depth_triggers._cik` read it flat, so it returned
`None` for **every ticker in the book**. `triggers_for()` guards the whole SEC block with
`if cik:`, so the 8-K trigger, the 10-Q/10-K filing trigger and the `filing_pending` defer gate
were dead from the day they were written. Only `move`, `rotation` and the new `pack` trigger were
ever alive.

This is the event-driven half of the cadence — the SanDisk-investor-day class, where an 8-K changes
the thesis between scheduled runs. It failed silently because "no CIK" degrades to "no filing
trigger today" by design, exactly as a genuine SEC outage would.

**Two signals were in plain sight and neither was questioned:** the depth queue printed
`class 0 event-triggered: 0` across all 171 names, and `cache/sec_submissions` held **0 files**
despite a docstring claiming ~172 requests a day. `tag_coverage_census.py:72` had always read the
file correctly; only this reader was wrong.

**Fixed** (`8722bb9`, then `44c627f`): GOOG now resolves and returns 80 filings since 2026-06-01
including an 8-K on 2026-08-10; the submissions cache populates. `_cik` moved into
`capability_test` and `depth_triggers` aliases it, so there is one reader instead of two that had
already disagreed once. Book-wide the fix adds one event-triggered name (PM), so it did not
disturb the running sweep.

## 7. The remaining hard-coded population counts

**Correction to an earlier draft of this document:** it listed *five* remaining counts including
"33 unmapped debt tags". That sentence no longer exists — it was removed in `ab5e4c3` when
SECTION 6B was added. Four remained, not five.

All four are now computed per company (`44c627f`), using `sec_facts` — one file per company, 3–4 MB,
~0.03s to parse. Book-wide results: `wtd-avg shares` resolves to **141 verified diluted, 7 matching
neither filed count, 13 whose newest fiscal year the 10-K index has not reached, 10 foreign filers
with no index** — and **zero** basic or undifferentiated, so the old "18 live names" claim has no
instance in this book at all. Capex disagrees on **48** names, over a measured range of
**0.64×–49.05×** against the frozen claim of 1.1×–42×; the 0.64× end also contradicts that
sentence's own reasoning that the vendor definition is the broader one.

**A proposed fix was tested and rejected.** I proposed releasing the withheld effective tax rate to
companies lacking the `…BeforeIncomeTaxesDomestic` tag, on the strength of one ticker. Measured
across the book, that gate **misses 14 of the 57 names whose identity actually fails and needlessly
condemns 73 of the 116 that pass** — 116 names carry the tag, not the 38 the pack claimed. The
identity `net_income + tax == pretax` is the better screen but is *necessary, not sufficient*: a
domestic-only pre-tax paired with a domestic-only tax is self-consistent and still not the
consolidated figure. **The rate stays withheld.** The pack now names the failing years per company
— disclosure, not release.

Scale check, since it bears on any future proposal to loosen this: the identity fails on **180 of
1,795 book rows (57 of 170 names)** but **6,461 of 39,671 corpus rows (1,762 of 4,606 names)**. A
wider universe is dirtier, not cleaner.

## What this sweep did NOT find

- No arithmetic error in the band-direction verdict rule, the spread computation or the size
  mapping. Re-derivation of all 29 published verdicts under the corrected guard changed **0**
  directions, which is independent evidence the verdict logic is stable.

## Open, and deliberately deferred

- **`SIZE_BUCKETS` is not an open calibration item — it is dead code with a face.** Corrected
  2026-08-25: `size_hint` is written and printed and **read by nothing**. Every reference is a
  display line (`depth_pipeline:204`, `status.py:242`, `depth_sanity:83`). Allocation happens
  downstream in the ledger strategies, which never see this field, and `publish_overlay` states
  that no site component reads the overlay yet. Re-deriving the buckets would change a label and
  nothing else. The real decision is whether to wire it into something or drop it — its only harm
  path is that it is shown to the operator and *looks* like advice, which is exactly how AVGO came
  to display `full` off a spread narrowed by a deleted sample.
- **Refreshing** `enrich/` and `cache/openbb_` inside the depth pipeline, rather than only stating
  their age. Deferred: it adds a network dependency per ticker to a sweep that currently has none.
- **The 7 share-count mismatches** (e.g. CRM's FY2025 row holding 974,000,000, which is its FY2024
  basic count). Fiscal-year labelling between our extractor and SEC's `fy` field is the plausible
  cause; not investigated. The pack reports these as UNVERIFIED rather than asserting a defect.
