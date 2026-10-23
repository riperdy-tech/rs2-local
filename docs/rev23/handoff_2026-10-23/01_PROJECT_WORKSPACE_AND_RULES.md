# 01. The project, the workspace, and the rules you must follow

## 1. What the project is

An automated stock-investment system for one operator (the user; email riperdy@gmail.com; they/them). The chain:

1. **The screener** (`stock-screener`, a Next.js site plus a Python data pipeline; the site is "stockpeak" on Vercel) scores the US-listed universe
   daily and nominates about 160 stocks ("research_now" top band about 50-60, plus a "watchlist") through the **Dual Door** (Door 1 quality, Door 2
   value, plus Door 3 trend leaders), a hygiene filter, a falling-knife floor and band hysteresis. "Charter v3.1 / dual door is the engine."
2. **The AI analyst** (`rs2-local`, "RS2") was supposed to value each nominated stock (undervalued / hold / overvalued) with a local model, publish
   verdicts to the site overlay, and drive a paper book and eventually real money through a broker connection (KIS).
3. **The macro engine** (`macro-regime-indicator`, "MRI") supplies the regime and capital-market anchors (risk-free rate, ERP, cost of equity).
4. **Real money** goes through KIS (Korea Investment & Securities) and is **halted** (`KIS_HALT=true` since 2026-09-22, after a real-money sync bought
   ARX unendorsed).

The analyst model: **Qwen 3.8 27B, Q5_K_M, with MTP**, Ollama tag `rs2-analyst-deep-mtp5-v33`, run through the project's own raw provider
`ollama_raw` (our own template and tool-call parser, because Ollama 0.40.3 dropped nested tool arguments). Ollama auto-updated to **0.40.6** on
10-20; the operator ruled "use it". The research model for deep research is `rs2-research` (14.8B Q4_K_M, about 12 GB).

Hardware: one PC, Windows 11, RTX 3090 24 GB, about **12 GB system RAM** (tight), Wi-Fi only (the wired adapter is disconnected). The operator
also games on this GPU.

## 2. The workspace (`C:\Users\riper\stocks`)

```
stocks/
├── stock-screener/           Next.js site + Python pipeline. Vercel deploys from its root. Local checkout is on an OLD branch (another session's).
├── rs2-local/                the analyst pipeline (PUBLIC GitHub repo: riperdy-tech/rs2-local). Real money depends on its verdicts.
├── macro-regime-indicator/   MRI, the macro engine and anchors (DuckDB store; another Claude session works on it).
├── rs2-state/                rs2 state backup via git (artifact store; no code).
├── screener-publish/         a DEDICATED clone of stock-screener used only for publishing the depth overlay. Never develop in it.
└── stocks-workspace/         cross-system docs, specs, scratch. Not one of the four systems. All the work of this session lives here and in rs2 branches.
```

Each repository has its own `AGENTS.md`; the workspace root `C:\Users\riper\stocks\AGENTS.md` loads first. **Nothing imports across repositories**;
handoffs are files on disk or git operations. Paths between repositories are resolved by resolvers (`rs2-local/paths.py`,
`stock-screener/scripts/peer_paths.py`, `macro-regime-indicator/src/macro_engine/peer_paths.py`) with env vars (`STOCKS_ROOT`, `SCREENER_DATA_DIR`,
`MRI_*`, `RS2_*`, ...). Never write an absolute path to a sibling repository in code.

## 3. The ten non-negotiables (from `stocks/AGENTS.md`)

1. Real money: every rs2 output is an underwriting proposal, not a demo.
2. No narrow heuristic patches: one ticker behaving oddly is a symptom of a systemic flaw. Fix the engine, never the ticker.
3. Annotate, never silently gate: new signals ride as flags and reasons on a verdict.
4. `0.0` is a value, not an absence. Never use `or` to default a numeric field.
5. Single owner per field: a new contract field must be added to its owner's schema.
6. Never publish the depth overlay from the shared screener tree; use `screener-publish`.
7. Changing what the model is told is a versioned decision (`PACK_REVISION`). (Operator 2026-09-27: you may change briefing text / pack revision
   without asking, but version it, record it and have it checked.)
8. Never deploy automatically.
9. Never delete files, edit secrets or `.env*`, or change CI or deployment config unless explicitly asked.
10. Review the diff and run the tests before declaring work done.

`rs2-local/AGENTS.md` adds a "standard of proof" section: no assumptions, no skipping, never build to fit available data, gaps are stop conditions,
prove with measured data from the repository.

## 4. The operator's standing rules (from the Claude memory directory; verify there)

Memory index: `C:\Users\riper\.claude\projects\C--Users-riper-stocks\memory\MEMORY.md`. The ones that matter most for this work:

- **The coordinator leads.** "Other AIs are teammates": outside reviews (ChatGPT, Gemini) are advice; the coordinator rules on each point and owns
  the real-money goal. The operator delegated the 10-22/23 rulings explicitly ("I rely on you as the total lead and mediator").
- **Fresh agents per task/review**; never resume one agent for hundreds of thousands of tokens (a quick follow-up in the same task is fine).
- **Audit every builder's work** before reporting: read the diff, recompute key numbers, check look-ahead and artifacts.
- **Parallel builders allowed** (operator 10-14), audited line by line before merge.
- **GPU standing go** (10-04): never ask before a GPU run; if another session holds the card, wait. **GPU is shared with gaming**: pause GPU jobs
  while the operator plays.
- **Smoke test before every long GPU run**; runners stop at the first code-defect failure (fail-fast).
- **Cross-check before GPU runs** (10-16): an outside-AI cross-check of work since the last one before a GPU run (the operator has waived this case by
  case; ask).
- **Long runs outside Claude**: launch multi-hour jobs via Windows scheduled tasks + hidden `.vbs` wrappers (a Claude app update once killed a run).
- **RAM limit**: about 12 GB; no heavy CPU sweeps while llama-server/Ollama has the analyst loaded (an out-of-memory crash happened 10-11 and 10-20).
- **rs2-local is PUBLIC**: scan every diff for secrets before each push; commit by pathspec in shared repositories; merges include the push
  ("merge means push").
- **SEC downloads: standing approval**; live SEC/Yahoo/Damodaran fetches are approved.
- **Claude builds, it is never part of the running system** (the analyst must be local; Claude/ChatGPT/Gemini are never in the decision path).
- **AI analyst is required** (10-15): "code-only is a baseline"; when an option removes the AI, say so in plain words.
- **Proceed without approval overnight** when the operator sleeps: decide, proceed, report; never burn a holdout on weak evidence.
- **Continuous non-GPU work**: during GPU runs, keep working through non-GPU items; stop only for operator decisions.
- **No Opus subagents** (10-02, partly superseded 10-10/10-14): the coordinator does reviews/judgments itself; builders may be general agents.
- **Research agents share a 200-call WebSearch cap** per session.
- **`ollama create` unloads a runner**: never build model tags while another session's model is loaded.

## 5. Safety state right now (verify before any action)

- `KIS_HALT` on: no real money moves. (Set in rs2's environment since 2026-09-22; do not touch secrets/.env.)
- `DEPTH_PAUSED` on: file `C:\Users\riper\stocks\rs2-local\cache\DEPTH_PAUSED` exists; the production analyst sweep does not run.
- Depth Cloud Backstop (GitHub Actions) disabled manually.
- `RS2-Baseline-Runner` scheduled task **removed** 2026-10-22 (operator); its definition saved as
  `stocks-workspace\scratch\baseline-2026-10\RS2-Baseline-Runner_task_removed_20261021.xml`; folder and its 33 results kept.
- `RS2-Shadow-V4` task removed 2026-10-20 (operator: "we don't use it any more"); its folder (`scratch/rev23/wt-d5-shadow`) and the rn_v4 paper books
  were left in place ("leave it for now").
- Nothing of this work is merged to rs2 `main` or deployed. All of it is on review branches and in the pilot folder.

## 6. Working style expected (from `AGENTS.md` and the operator)

- State assumptions; if unclear, ask. Simplicity first. Surgical changes. Goal-driven: turn tasks into verifiable goals.
- **Correct yourself in the same breath** when a check contradicts something you said.
- Report outcomes faithfully: failed tests, skipped steps, numbers as measured.
- The operator writes short messages ("do both", "yes", "no waiting do it now", "do all"); they expect you to act, keep them informed in a few lines,
  and ask only for real decisions. They dislike wasted time on avoidable bugs ("I can't believe you wasted so much time on a stupid bug").
- The operator sometimes pastes ChatGPT/Gemini replies; you rule on them point by point (file 09).
- The session used "caveman mode" (terse output style) for chat replies; documents and commit messages are normal prose.
