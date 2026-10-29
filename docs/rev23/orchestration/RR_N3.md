# RR_N3: discovery, frame, draw and controls (builder report, 2026-10-29)

Work order: `WO_N3.md`. Spec and PREREG followed as frozen; nothing in them was changed. No event was labelled or judged.
Folder: `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3n\`.

## What exists

| File | Role |
|---|---|
| `frame.py` | `frame_commits()`, `frame_at(T)`, `rows_at(commit)`, `cik_map_at(commit)`, `symbol_union()`, `name_union()` (plus `cik_union()`, `norm_name()`). Caches in `frame/` (`commits.json`, `rows/<hash>.json.gz`, `unions.json`). |
| `discover.py` | FTS channel, item-code channels, pre-filter. Writes `candidates.jsonl`, `discovery_dropped.jsonl`, `discovery_summary.json`. |
| `draw.py` | The per-class draw and queue. Writes `queue/<class>.jsonl`, `queue/skipped.jsonl`, `queue/cover_parses.jsonl`, `queue/state.json`. `--class C2 --more 6` extends in the same order (tested on a copy of the queue: the first 12 were unchanged, 6 more were added, then the copy was deleted). |
| `controls.py` | The 48 controls. Writes `controls.jsonl` and `controls_draw_log.jsonl` (every draw with its fate). |
| `sec_fetch.py` | Fetcher: SEC hosts only, at most 4.76 requests a second across threads (0.21 s slot), `raw/<sha256>` plus `raw/receipts.jsonl`, never refetches a stored 200 or 404. |

`m3n/baseline_b.py` is not mine; it appeared in the folder while I worked. I did not read it or touch it.

Python: `C:\Program Files\Python312\python.exe`, standard library, plus `exchange_calendars` 4.13.2 and pandas through `qwen_c.packet` (the tools that import `packet` therefore cannot run with `-I`, which hides the user site-packages). Bytecode writing was switched off; nothing was written to `wt-m3m`, to `stock-screener` or to any repository.

## Correction from the lead (frame ref), applied

The lead said not to use HEAD and to pin `origin/main` by sha. `frame.py` was already built on the ref `origin/main`, never HEAD. `git rev-parse origin/main` gives `92592e2156105809da6126c4d11b206aaec9a7a1`, and the cached commit list was built from exactly that tip (`ref_tip` in the file was the same sha), so nothing had to be rebuilt and no draw had to be redone. `frame.py` now resolves the sha once, records `"ref": "origin/main"` and `"ref_sha"` in `frame/commits.json`, and runs every `git log` and `git show` on the sha. I added `rev-parse` to the allowed git commands on the screener checkout (read only); all others stay `log`, `show` and `cat-file`. I added the `ref_sha` field to the existing `commits.json` by hand (same value) rather than re-listing. No fetch was run.

## Frame facts

- `origin/main` has 274 commits touching `public/data/stocks.json` (first 2025-12-14T14:12:27Z, 1,991 rows; next 2026-04-05; last 2026-10-29T01:13:26Z, 7,012 rows). Local `main` is stale (2026-09-02) and HEAD is another session's feature branch.
- `cik_map.json` exists from the 2026-06-11 commit on (one version in history). So 38 of the 48 controls and every queued event whose T1 is before 2026-06-11 have no cik_map cross-check.
- `frame_at(T)` is None before 2025-12-14T14:12:27Z. Every T1 and control T in the window has a frame.
- Unions over all 274 commits: 7,094 symbols, 7,293 normalised names, 8,009 CIKs.
- `stocks.json` rows include non-common securities (baby bonds, preferreds such as RILYT, TMUSL, DTG) and some names truncated at 31 characters (for example "Stablecoin Development Corporat"). Both matter to membership and to control CIK matching.

## Discovery

- **FTS:** 273 search requests (PREREG queries, per calendar month, 2025-12-15 to 2026-09-30). No window reached 10,000 hits, so no half-month or day split was needed (`split_log` is empty). 21,519 hit rows in all.
- **Item-code channels:** the FTS `items` field (any hit whose items contain a class's code creates a candidate for that class, `item_code_fts`), and a submissions-JSON sweep (`item_code_submissions`) of 8-K and 8-K/A rows filed in the window. The sweep set is the CIKs of every frame cik_map (8,009) plus the CIKs of the FTS hits the pre-filter kept (3,744; 98 of them not in any cik_map): 8,107 CIKs, 0 returned 404.
- **Pre-filter** is applied to FTS hits only (hit by CIK). Kept: any of CIK in a frame cik_map, a display-name ticker in `symbol_union`, normalised name in `name_union`. 4,503 hit-CIK pairs were dropped by all three and are in `discovery_dropped.jsonl`. Per class counts of each test, and of "kept only by one test", are in `discovery_summary.json` (`prefilter_by_class_over_hit_ciks`). The CIK test alone kept 2,521 hit-CIK pairs (summed over classes) that the other two tests missed; the ticker test alone kept 56 and the name test alone 15 (sums over classes).

Candidates (cik, class, accession), merged across channels:

| Class | Candidates | Issuers | Channel mix (set of channels per candidate) |
|---|---|---|---|
| C1 | 81 | 48 | fts only 34; fts+item_fts+item_sub 18; item_fts+item_sub 19; item_sub only 10 |
| C2 | 4,184 | 1,599 | fts only 4,184 |
| C3 | 110 | 98 | fts 32; all three 65; item_fts+item_sub 1; item_sub 12 |
| C4 | 1,450 | 829 | fts 429; all three 1,007; item_fts+item_sub 4; item_sub 10 |
| C5 | 8,702 | 3,387 | fts 676; all three 849; item_fts+item_sub 2,921; item_sub 4,256 |
| C6 | 738 | 644 | fts 20; all three 672; item_fts+item_sub 28; item_sub 18 |
| C7 | 2,118 | 1,523 | fts only 2,118 |
| C8 | 3,864 | 2,064 | fts 3,789; all three 74; item_sub 1 |
| Total | 21,247 | | |

Per month counts are in `discovery_summary.json`.

## Draw (queue to 12 per class)

T1 is `qwen_c.packet.effective_at(qwen_c.packet.accepted_at(acceptanceDateTime))` from `wt-m3m/qwen_c/packet.py`, policy `sec_acceptance_next_full_xnys_session_late_after_1730_plus_one_v1`. Classes ran C1 to C8 in that order; an issuer queued in an earlier class is skipped in later ones.

| Class | Candidates in pool | Positions walked | Queued | eligible | needs_review | Skipped: symbol_not_in_frame | no_cover_symbol | issuer_already_queued | outside_event_window |
|---|---|---|---|---|---|---|---|---|---|
| C1 | 81 | 29 | 12 | 11 | 1 | 13 | 2 | 2 | 0 |
| C2 | 4,184 | 30 | 12 | 12 | 0 | 6 | 11 | 1 | 0 |
| C3 | 110 | 14 | 12 | 11 | 1 | 2 | 0 | 0 | 0 |
| C4 | 1,450 | 15 | 12 | 12 | 0 | 2 | 0 | 1 | 0 |
| C5 | 8,702 | 17 | 12 | 12 | 0 | 4 | 0 | 1 | 0 |
| C6 | 738 | 16 | 12 | 11 | 1 | 2 | 0 | 1 | 1 |
| C7 | 2,118 | 18 | 12 | 12 | 0 | 6 | 0 | 0 | 0 |
| C8 | 3,864 | 18 | 12 | 11 | 1 | 3 | 2 | 1 | 0 |
| Total | | | 96 | 92 | 4 | 38 | 15 | 7 | 1 |

No candidate was skipped for an excluded ticker. The queue is deterministic (a full rerun from scratch gave identical positions).

The four `needs_review`: C1 ADI Global Distribution (frame name is the ticker "ADIG"); C3 Stablecoin Development Corp (frame name truncated); C6 Hecla Mining ("CO/DE/" suffix in the SEC name); C8 Public Service Co of New Mexico (cover symbol TXNM, the frame's cik_map maps TXNM to a different CIK, 0001108426: a cik_map disagreement downgrades `eligible` to `needs_review`).

Queue records hold: the candidate, `acceptance_utc` and `acceptance_raw`, `T1`, frame commit, event-filing form and items, cover symbols, cover cells, parse method, cover text, membership (`verdict`, `cover_symbol`, `frame_symbol`, `frame_name`, `names_agree`, `cik_crosscheck`, `names_compared`), and for C2 `preceding_periodic_report`. For C2 that field is filled for 11 of 12; the 12th has no earlier 10-Q/10-K/20-F in the issuer's submissions (null).

Stale frame: 11 of the 96 queued events have T1 before 2026-04-05, so their frame is the 2025-12-14 snapshot.

## Cover-symbol parse

- **Method:** (1) the inline-XBRL facts `dei:TradingSymbol` (all `ix:nonNumeric` tags in the document), split on commas, spaces and slashes; (2) when there is no such tag, a text heuristic: capital-letter tokens right before an exchange name in the cover text (stop-list of words such as STOCK, COMMON, LLC). The cover text kept is the plain text from the document start to just after "emerging growth company" (capped at 8,000 characters). The `ix:header` block is removed first.
- **Event filings parsed: 149** (114 8-K, 24 10-Q, 9 10-K, 2 8-K/A). 132 gave at least one symbol, all by method 1 (parse rate **88.6%**). 17 gave none; for the ones I opened (CUMULUS, KBS REIT III, Lipella, Cloudweb, Magellan, Rapid Line and others) the cover really says N/A or None, or lists no Section 12(b) security. Method 2 never fired on a real document; I tested it on synthetic cover HTML only (it found XYZ and XYZW).
- **Fallback to the issuer's last periodic report** was tried for the 17: 2 gave a symbol (queued with `cover_source: prior_periodic_report`), 15 gave none, and those 15 candidates are the `no_cover_symbol` skips (companies with no exchange-listed security). Every parse attempt is in `queue/cover_parses.jsonl`.

## Controls

- **Sessions:** `exchange_calendars` 4.13.2 (XNYS, the calendar object `packet.py` uses): 199 sessions from 2025-12-15 to 2026-09-30.
- **Draws:** 86 draws gave 48 controls; 36 were excluded and replaced, 2 unresolved and replaced, 48 accepted. Split by accepted control number: 24 DEV (odd), 24 FRESH (even). No CIK appears twice.
- **CIK source:** 10 from the frame's cik_map, 38 from `https://www.sec.gov/files/company_tickers.json` by ticker. The name lookup and the EDGAR company suggest (`https://efts.sec.gov/LATEST/search-index?keysTyped=<normalised name>`, `_id` = CIK) are coded and were used only for the 2 unresolved draws (3 suggest requests; neither draw found a verifying CIK).
- **Verification** against the submissions name or `formerNames` in force at T: 44 `exact` (PREREG normalisation) and 4 `loose`. The 2 unresolved draws were draw 19 (MAYS, J.W. Mays, Inc.: SEC name "MAYS J W INC") and draw 85 (DTG, a DTE Energy debt security row); both failed on name and were replaced.
- **Exclusions (36):** 151 candidate hits inside [T-180d, T+30d], all timed by the acceptance time from the issuer's submissions. Hits per class: C5 52, C2 30, C8 27, C4 19, C7 14, C6 7, C3 1, C1 1. Draws on the 2025-12-14 frame lost 8 of 39 (21%); draws on later frames lost 28 of 47 (60%). As a result 31 of the 48 controls sit on the stale 2025-12-14 frame (1,991 rows), against about 38% of sessions that fall before 2026-04-05.
- Each control carries its issuer's filings accepted in [T-180d, T] (3 to 106 per control), with form, accession, acceptance time (UTC and raw) and 8-K items.

## Requests

All 8,563 requests ever sent returned HTTP 200 (no retries, no 404, no 429), 775 MB stored; 8,563 unique URLs.

| Kind | Requests | Host |
|---|---|---|
| FTS search pages | 273 | efts.sec.gov |
| EDGAR company suggest | 5 (2 format probes, 3 in controls) | efts.sec.gov |
| submissions JSON (8,107 CIKs, plus 1 older `files` page) | 8,108 | data.sec.gov |
| filing primary documents | 176 | www.sec.gov |
| company_tickers.json | 1 | www.sec.gov |

The 176 documents include 149 event-filing covers, 17 prior-report fallbacks and 10 fetched by my test of `--more 6` on a copy of the queue (those 10 are stored, not in the delivered queue; they would be reused by a real `--more`). Window: 2026-10-29T04:41:50Z to 05:23:27Z. Rate: 4.76 per second at most. The sweep ran with 4 threads sharing the one throttle; I kept other requests out of its way.

## Choices the brief did not fix

1. **Frame ref:** `origin/main`, pinned at `92592e21...` (see the correction above).
2. **Name normalisation:** PREREG rule applied as: case-fold, `&` to "and", every non-alphanumeric run to a space, then trailing `inc, incorporated, corp, corporation, ltd, limited, plc, co, company` removed repeatedly. The long forms are mine. It does not strip "/DE/" style qualifiers or a leading "the". This yields `needs_review` for names such as "HECLA MINING CO/DE/" (kept, not dropped).
3. **Control CIK verification** uses a looser key (accents and apostrophes removed, text after the first "/" dropped, leading "the" dropped, long suffix words shortened) as a second level, `loose`. Without it, about 9% of cik_map rows failed on cosmetic differences (Casey's, VERTEX ... /MA, STANDEX ... /DE/). The level is recorded per control. This key is used only for controls.
4. **Control draw mechanics:** each draw consumes one value of each rng (date from `/control_dates`, row from `/controls`); rows sorted by symbol before indexing, excluded tickers removed. The split uses the accepted control number (1 to 48), not the raw draw index, so it is 24/24. Both numbers are in the file.
5. **Control exclusion** is by CIK (same issuer), with all candidate classes, including noisy ones (every C2 FTS hit and every 8-K with item 1.01). The 8-K/A rows count.
6. **Item-code channels:** the FTS `items` field creates candidates for other classes too (a C8 query hit carrying item 1.03 is a C1 candidate). The submissions sweep includes 8-K/A.
7. **Primary document:** always the submissions `primaryDocument` of the accession (the FTS hit document, which can be an exhibit, is kept as `fts_hit_ids` only).
8. **Membership extras:** the CIK cross-check against the frame cik_map is recorded; a disagreement downgrades `eligible` to `needs_review`. The names compared are the FTS display name, the submissions name and every `formerNames` entry, and the ix `EntityRegistrantName`. Cover symbols are also tried with `.` and `-` swapped. When the event filing has no cover symbol, the issuer's last 10-Q/10-K/20-F cover is used.
9. **Issuer identity** for "one event per issuer": the CIK, and also the matched frame symbol.
10. **Preceding periodic report (C2):** the latest 10-Q, 10-K or 20-F (no amendments) with acceptance before the event filing, from the submissions pages that end after 2025-01-01.
11. **Window test** is on the SEC acceptance time (as read by `accepted_at`), so a filing with file date 2026-09-30 can fall outside the window; one C6 candidate was skipped that way (acceptance 2026-10-01T00:25:20Z).
12. **Order of classes** in the initial draw is C1 to C8.

## Things that look wrong or odd, for the reviewer

- **Acceptance clock.** Submissions `acceptanceDateTime` is Z-suffixed, but `accepted_at()` takes the later of the UTC and the Eastern-wall-clock readings, so `acceptance_utc` is 4 to 5 hours after `acceptance_raw` for most filings (for example a 20:15 "Z" filing with file date 04-17 is read as 2026-04-18T00:15:32Z, T1 2026-04-21). I used `accepted_at` as is and recorded both values.
- **Control time vs session open.** PREREG fixes T at 14:30:00Z. That is the 09:30 ET open only in winter. From 2026-03-09 the NYSE opens at 13:30Z, so a summer control T is one hour after the open, while the queue's T1 values (from `effective_at`) are 13:30Z. I followed PREREG.
- **Exclusion skews the controls toward the stale frame** (see above), and the PREREG exclusion rule removes issuers with any 1.01 8-K in the window. Controls therefore lean toward quieter issuers on newer frames.
- **C5 and C6 pools are noisy by construction** (every item 1.01 or 2.01 8-K of a frame CIK is a candidate: 7,177 of the 8,702 C5 candidates came only through the item channels). The 12 C5 queue entries are mixed: 7 reached only through the item channels (6 submissions only, 1 FTS items plus submissions), 2 through FTS text only, 3 through all channels. Reviewers should expect many non-events and may need `--more`.
- **C2 pool is boilerplate-heavy** (every 10-Q/10-K matching "substantial doubt" and "going concern", including "no substantial doubt" sentences). 11 of the 12 C2 queue items are 10-Q, 1 is a 10-K.
- **Dead names:** the item-code sweep reaches only frame CIKs and CIKs of kept FTS hits; a company that died before 2026-06 and was missed by every FTS query is unreachable. The pre-filter dropped 26 C1 hit-CIK pairs (all three tests failed); `discovery_dropped.jsonl` lists them.
- **Controls need the current company-ticker file** for most CIKs (38 of 48), which lists only companies that still have a ticker; a dead name in the stale frame cannot resolve that way. The EDGAR suggest fallback did not rescue the 2 unresolved draws. Survivorship is therefore possible in the controls drawn from old frames.
- The first run of `draw.py` had a stray backspace character in a regex (my heredoc); it only affected the informational `none_stated` flag, was found and fixed, and the draw was rerun from scratch from stored responses (0 new requests). Final outputs are from the fixed code.

## Output fingerprints (sha256, first 16 hex)

`candidates.jsonl` 8f00da00c0673928; `controls.jsonl` f24a34b6c3760672; `queue/state.json` c844b14829a13482.
