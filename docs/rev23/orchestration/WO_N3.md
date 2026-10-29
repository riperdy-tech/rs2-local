# WO_N3: 3N discovery, frame and draw tools (builder brief, 2026-10-29)

**Read first:** `SPEC_m3n_event_validation.md` (§1, §2, §4) and `PREREG_m3n.json`, in this folder. Both are frozen; follow them exactly. Also read `C:\Users\riper\stocks\AGENTS.md`.

**Where to work:**
- **Folder:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3n\`. It is scratch, not a repository; create it.
- **Do not write to:**
  - any repository;
  - any `.env*` or secrets file.
- **The stock-screener development checkout** (`C:\Users\riper\stocks\stock-screener`) may be read ONLY through `git log`, `git show` and `git cat-file`. No checkout, no other git command. Another session may be using it.
- **Python:** `"C:\Program Files\Python312\python.exe"`. Use the standard library unless something truly needs more.

**Network:** SEC only (standing approval).
- Hosts: `efts.sec.gov`, `www.sec.gov` and `data.sec.gov`.
- Send the User-Agent header from `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3m\qwen_c\sec_store.py` (`UA`). Import it by `sys.path`, or copy the string.
- At most 5 requests a second.
- Save every response under `m3n/raw/` by sha256, with a `receipts.jsonl` line (url, sha256, bytes, status, fetched_utc).
- Never refetch what is stored.

## Tools

### 1. `frame.py`

- `frame_commits()`: every stock-screener commit touching `public/data/stocks.json` (hash, committer time in UTC), cached to `m3n/frame/commits.json`.
- `frame_at(T)`: the last commit with committer time ≤ T. Return None before the first commit.
- `rows_at(commit)`: symbol, name and other fields, cached per commit.
- `cik_map_at(commit)` where present.
- `symbol_union()` and `name_union()` over all commits, with the PREREG name normalisation.

### 2. `discover.py`

- **The FTS channel.** Run PREREG `discovery.fts_queries` per class, split by calendar month over the event window. Page through all hits; if a month exceeds 10,000 hits, split it by half-month and record that.
- **The item-code channel.** Use the FTS `items` field, and, for pre-filtered CIKs, the submissions JSON 8-K `items`.
- **Pre-filter** (keep a hit when any of these holds):
  - its CIK is in any frame `cik_map`;
  - a ticker shown in `display_names` is in `symbol_union()`;
  - its normalised name is in `name_union()`.

  Do NOT drop on any other ground: a company that died before 2026-06 appears only in old snapshots, by name. Count what each test kept and dropped.
- **Output:** `m3n/candidates.jsonl`, one line per (cik, class, accession), with the channels merged. Fields:
  - cik, entity names, accession, form, file_date, items;
  - class, channels;
  - the FTS hit id (the document file);
  - pre-filter reason.

  Also `m3n/discovery_summary.json`, with counts per class, month, channel and pre-filter test.

### 3. `draw.py`

- **Order.** Per class, sort candidates by (cik, accession), then shuffle with `random.Random(int(sha256((seed + '/events/' + class).encode()).hexdigest(), 16))`.
- **Walking the order,** for each candidate:
  - **(a)** fetch the submissions JSON (`data.sec.gov/submissions/CIK##########.json`, plus the extra `files` pages if needed) to get the filing's `acceptanceDateTime`;
  - **(b)** compute T1 with the acceptance rule. Import `effective_at` (or the equivalent) from `wt-m3m/qwen_c/packet.py`; find the function there and record which one you used;
  - **(c)** find the frame commit at T1;
  - **(d)** fetch the filing's primary document and read the cover-page trading symbol(s). Report how you parse it, and keep the parsed cover text;
  - **(e)** decide membership: the symbol is in the frame's `stocks.json` and the names agree (PREREG normalisation). A symbol match with a name mismatch is `needs_review`, not dropped;
  - **(f)** skip excluded tickers, and an issuer already queued in another class (one event per issuer).
- **Stop** a class after 12 eligible-or-needs_review candidates. Write `m3n/queue/<class>.jsonl` in draw order: candidate, acceptance time, T1, frame commit, cover symbols, membership verdict, and for C2 the accession and acceptance time of the issuer's preceding periodic report (10-Q/10-K/20-F).
- **Every skip** is recorded with its reason in `m3n/queue/skipped.jsonl`.
- **CLI:** `--class C2 --more 6` extends a class's queue in the same order.

### 4. `controls.py`

- **Draws,** per PREREG `controls`:
  - the XNYS session dates of the window. Use `exchange_calendars` if installed; otherwise build them from weekdays minus the NYSE holidays of 2025–2026, listed explicitly in the code, and report which;
  - the row draws with the `/controls` and `/control_dates` seeds.
- **CIK:** from the frame's `cik_map` where present. Otherwise use an EDGAR name lookup, and say which endpoint you used. Verify the name against the submissions name and `formerNames` at T. Unresolved: replace, and record.
- **Exclusion,** per PREREG, against `candidates.jsonl`. Every exclusion is recorded.
- **Output:** `m3n/controls.jsonl`: draw index, split (odd DEV, even FRESH), T, frame commit, symbol, name, cik, cik source. For each control, also the list of the issuer's filings accepted in [T−180d, T] (form, accession, acceptance time, 8-K items), for the reviewer.

## Run it

Run all four for real:
- discovery over the whole window;
- the draw to 12 per class;
- the 48 controls.

## Report

Write `RR_N3.md` in the orchestration folder. It covers:
- what ran and the counts;
- request totals;
- every choice this brief did not fix;
- the cover-symbol parse rate;
- anything that looks wrong.

Do not label any event, and do not judge whether one is critical. That is reviewer work (N4).
