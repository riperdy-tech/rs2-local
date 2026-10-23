# Session handoff, 2026-10-23: START HERE

Written 2026-10-23 by the coordinator (Claude, Opus 5.5) at the end of a long session that ran from 2026-10-18 to 2026-10-23. It is meant for a
brand-new AI (or human) that knows nothing about this project. Read the files in order. Each is self-contained enough to act on, and each names
the source records it summarizes, so you can verify anything before you act on it.

**Read these in this order:**

| # | File | What it gives you |
|---|---|---|
| 00 | this file | orientation, the one-paragraph state, what to do first |
| 01 | `01_PROJECT_WORKSPACE_AND_RULES.md` | what the project is, the four repositories, the operator's standing rules, the non-negotiables, safety state |
| 02 | `02_STATE_OF_PLAY_AND_DECISION_PENDING.md` | exactly where things stand today and the decision the operator has to make next |
| 03 | `03_CHRONOLOGY_2026-10-18_TO_10-23.md` | what happened, day by day, with commits |
| 04 | `04_REVISION26_DESIGN_HARNESS_AND_HOW_TO_RUN.md` | the staged analyst, the pilot harness, the run file, flags, tasks, how to relaunch anything |
| 05 | `05_RESULTS_ALL_MEASUREMENTS.md` | every result: iterations 1-4, readers, scorecards, canaries, engine measurement, baseline A, the cutoff probe |
| 06 | `06_CODE_BRANCHES_COMMITS_AND_PATHS.md` | every branch, commit, worktree, folder and file that matters |
| 07 | `07_OPEN_ITEMS_AND_NEXT_STEPS.md` | the pending decisions, the recommended next actions, the deferred list |
| 08 | `08_OPERATIONS_AND_GOTCHAS.md` | everything that bit us: Wi-Fi, search engines, keys, RAM, GPU sharing, Ollama, exit flags, CRLF, git rules |
| 09 | `09_CROSS_CHECK_PROTOCOL_AND_RULINGS.md` | how the outside-AI cross-checks (ChatGPT, Gemini) work and every ruling from 21 to 25 + post-freeze |
| 10 | `10_GLOSSARY.md` | the project's vocabulary |
| 11 | `11_AGENT_PROMPT_TEMPLATES.md` | the exact prompts used for readers, builders, measurement and GPU-probe agents |

## The state in one paragraph

The project tried to build a local AI analyst (Qwen 3.8 27B, Q5_K_M, on one RTX 3090) that values US stocks so that real money can follow its
verdicts. Over 2026-10-18..23 a four-stage "staged analyst" design (revision 26) was built, benchmarked on 12 stocks across four iterations and
**frozen on 2026-10-23 as "paper-only, low confidence"**: it never loops, never copies revealed numbers, and is immune to anchoring, but only 0-1 of 9
analyses were judged fully coherent by blind readers (it argues long-run margin premiums from short evidence and its memos drift from its own
inputs), and several valuations are 2-4x the price because of both optimistic forecasts and a real desk defect (the kappa / year-6 cash-flow
inconsistency). A new direction was then drafted (`SPEC_factor_led_v1.md`: the screener selects, Python enforces risk and exits, the AI investigates
and monitors, valuation is diagnostic). **But the last measurement, baseline A, found the screener itself has no stock-picking edge after factor
controls over 2017-2025** (all its edge came from 2023-24). So no component of the system has a demonstrated edge yet. The operator must now choose
the strategic direction (file 02). Trading is halted (`KIS_HALT`), the analyst sweep is paused (`DEPTH_PAUSED`), nothing is running on the GPU.

## What to do first (in this order)

1. Read files 01 and 02 completely. Do not start any run, task or code change before you have.
2. Check nothing is running: `nvidia-smi`, `ollama ps`, and `schtasks /Query /FO LIST` for RS2-* tasks in state "Running" (file 04, section 9).
3. Read your memory index if you are a Claude Code session in this workspace: `C:\Users\riper\.claude\projects\C--Users-riper-stocks\memory\MEMORY.md`.
   The handoff assumes those rules (file 01 restates the ones that matter).
4. Ask the operator for the strategic decision in file 02 (unless they already gave it). Present the three paths and the recommendation.
5. Whatever is chosen, follow file 07's "next steps" for that path.

## The most important sources (all mirrored to GitHub)

- Records folder: `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\rev23\` (local), mirrored to the public repository
  `github.com/riperdy-tech/rs2-local`, branch `docs/rev23-records`, folder `docs/rev23/` (local worktree of that branch:
  `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\wt-docs`).
- The running log: `rev23/PLAN_terminal_reinvestment.md` (836+ lines; its end sections cover 10-19..10-23 in detail).
- The frozen design: `rev23/SPEC_rev26_staged_analyst.md` (sections 1-8 design; 9 Amendment 1; 10 Amendment 2; 11 Amendment 3).
- The next-design draft: `rev23/SPEC_factor_led_v1.md`.
- Cross-checks: `rev23/CROSS_CHECK_21_*.md` .. `CROSS_CHECK_25_sample_spread.md`.
- The one-page project status: `C:\Users\riper\stocks\stocks-workspace\docs\review_2026-09-22\STATUS.md` (Phase 4 section rewritten 10-22; not
  updated with the freeze or baseline A yet; see file 07).
- Code: rs2 branch `review-2026-10/r26-int` @ `c255803` (local worktree `scratch\rev23\wt-r26-int`).
- Durable copies of session artifacts (engine measurement, reader folders with extracts and JSON, helper scripts, task XMLs):
  `stocks-workspace\scratch\rev23\handoff_artifacts_2026-10-23\`.
- Baseline A: `stocks-workspace\scratch\baselineA\REPORT_baselineA.md`. The Qwen cutoff probe: `stocks-workspace\scratch\qwen_cutoff\REPORT_cutoff.md`.
