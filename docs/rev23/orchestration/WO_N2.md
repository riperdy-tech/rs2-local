# WO_N2: qwen_c v3 for 3N (builder brief, 2026-10-29)

**Read first:**
- `SPEC_m3n_event_validation.md` §2–§3 and `PREREG_m3n.json` (same folder);
- the 3M spec `SPEC_m3m_qwen_pipeline.md` with Amendments 1 and 2;
- `C:\Users\riper\stocks\AGENTS.md` and the repository's `AGENTS.md`.

**Where to work:**
- **Worktree:** `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-m3n`, branch `review-2026-10/m3n`, which starts at `bac4cf8`. Work only in `qwen_c/`.
- **Do not:**
  - push;
  - touch any other repository;
  - fetch anything from the network;
  - run a GPU job.
- **Commits:** commit by pathspec, with clear messages ending in `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- **Style:** match the existing code: its comment density, naming, docstrings that state the rules, and test style. Where this brief and the code disagree, stop and report the disagreement; do not guess.
- **Tests:** `"C:\Program Files\Python312\python.exe" -m pytest qwen_c/tests -q` (268 pass at start). Every change needs tests.

## 1. The `material_events` task (tasks.py)

**Placement.** Append `"material_events"` at the END of `TASKS`, so the existing tasks keep their seed indexes (seed = base + task index). `PROMPT_VERSION = "m3m.prompt.v3"`. The SYSTEM text stays unchanged.

**The task text**, in the style of the others:

> TASK material_events. List every material event that the evidence shows HAS OCCURRED or HAS BEEN FORMALLY ANNOUNCED (filed or published), one claim per event. A risk that could happen is not an event; risk-factor language ("could", "may", "if") is never an event. "event_type" is one of: bankruptcy_or_restructuring, going_concern_doubt, restatement_or_non_reliance, delisting_notice, acquisition_of_the_company, contract_loss, guidance_withdrawal, debt_default_or_acceleration, material_impairment, auditor_change, trading_halt, other_material_event. "status" is occurred or announced_pending. "occurred_on" is the date as an item prints it, or "not stated". Cite the item that reports the event and quote it. If the evidence shows no such event, return no claims and one unknowns line saying the evidence shows no material event.

**Reply shape:** `_shape("material_events", ...)` with the three fields.

**Pins and tests:**
- Keep the v1 and v2 pin sets in `test_tasks.py`, and add v3 pins for all eight tasks, generated the way the existing pins were.
- Only the new task's text is new.
- Check whether any existing v2 pin changes. It must not.

## 2. Contract v2 (contract.py)

- **Version.** `CONTRACT = "m3m.analysis.v2"`. `TASK_IDS` gains `material_events`.
- **Fields.**
  - Add `EVENT_TYPES` (the 12 above) and `EVENT_STATUSES = ("occurred", "announced_pending")`.
  - `TASK_EXTRA["material_events"]`: `event_type` (enum), `status` (enum), `occurred_on` (str).
  - A missing field or a wrong value is a shape error, exactly like `risk_type`.
- **Unchanged:** all citation, quote and figure checks. The module docstring's THE SHAPE paragraph names the new fields.
- **Tests:** a valid event claim; a bad `event_type`; a bad `status`; a missing `occurred_on`; an empty reply (malformed); no claims with one unknowns line (ok).

## 3. The packet (packet.py)

**Items.** `OTHER_8K_ITEMS` gains `"1.02"`. `BUILDER_VERSION = "m3m.packet.builder.v4"`.

**The archival regime.** `build(...)` gains `regime="verified"` (the default; the 3M behaviour is unchanged) and `regime="archival_sec_acceptance_v1"`. Under the archival regime:
- **No verified record.** None is needed or read. The header's `screener` block carries:
  - `"regime": "archival_sec_acceptance_v1"`;
  - `"screener_commit_verified": false`;
  - `"commit_time_utc"`: the committer time of the screener commit, in UTC Z form;
  - `"verified_row": null`.
- **Refusals:**
  - the commit's committer time is after T: refuse with `frame_commit_after_T`;
  - the commit does not touch `public/data/stocks.json` at or before itself: refuse.
- **The screener repository** is a `screener_repo_path` argument. The default is unchanged. Under the archival regime the caller passes the stock-screener development checkout. Read it only through git (`git show` / `git cat-file`). Never write it.
- **CIK.** When the commit has no `public/data/cik_map.json`, or it lacks the ticker, a `cik` argument must be given. The header records `"cik_source": "cik_map" | "argument"`. With both present and disagreeing, refuse with `cik_conflict`.
- **Packet top level:** `"regime"`, in both regimes (`"verified"` or the archival name).
- **Unchanged:** evidence selection, the acceptance rule, caps and the excluded tickers.
- **CLI:** `--regime {verified,archival_sec_acceptance_v1}`, `--screener-repo PATH`, `--cik`. `--verified-record` is required only for `verified`.

**Replay (replay.py).** Replay rebuilds archival packets offline, byte-identical, from the header (regime, commit, cik and its source). Add tests:
- an archival packet replays;
- a commit after T is refused;
- the cik conflict;
- a verified packet built at v3 still replays under its own `builder_version`. If replay can only rebuild the current builder version, say so in your report rather than inventing compatibility.

## 4. The runner (runner.py)

- **`--tasks`** (a comma list, each one of `TASKS`): run only those, in `TASKS` order. The manifest records `"tasks_requested"`. The run is `complete` when every requested task is ok.
- **`thesis_change`** runs only when requested. Its `not_applicable_no_prior` logic is unchanged.
- **`--seed-base`** (default 1000): seeds are `seed_base + task index`, and the malformed-retry offset is unchanged. The manifest records `seed_base` in `options`.
- **Unchanged:** everything else. Tests use the stub server, as the existing runner tests do.

## 5. Report

Write `RR_N2.md` in the same orchestration folder. It covers:
- the commits;
- the test count;
- every place where you had to choose something this brief does not fix;
- anything you found wrong.

Do not edit any other record.
