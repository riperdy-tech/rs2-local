# 09. The cross-check protocol and every ruling of this window

## 1. How cross-checks work
- The coordinator writes a self-contained `CROSS_CHECK_<n>_<topic>.md` in `rev23/` (background, what was measured, options with a recommendation,
  numbered questions, "give a one-line recommendation and the result you would most expect to fail"). It is mirrored to GitHub (`docs/rev23-records`)
  so the outside AIs can open it by link:
  `https://github.com/riperdy-tech/rs2-local/blob/docs/rev23-records/docs/rev23/<file>` (raw:
  `https://raw.githubusercontent.com/riperdy-tech/rs2-local/docs/rev23-records/docs/rev23/<file>`).
- The **operator** pastes it to ChatGPT and Gemini and pastes their replies back (sometimes as a shared ChatGPT link; read it with the browser tool).
- The **coordinator rules on each point** (adopt / modify / reject, with the reason), records the rulings in the plan log and, when they change the
  design, as a SPEC amendment registered **before** the next run. The operator approves or has delegated.
- Rulings must respect the non-negotiables (annotate don't gate; no narrow patches; 0.0 is a value) and the earlier rulings (e.g. "code must not
  substitute its judgment for the analyst's": an automatic code fade was rejected; prescriptive wording was rejected).
- Registration discipline: bars and protocols are fixed before results are read; when that is impossible, disclose it (Amendment 3 did).

## 2. Cross-checks 21-25 (summaries; read the files for full text)
- **21** (D2 coverage and the short form): ChatGPT CHANGE, Gemini CHANGE then GO. Rulings: τ·A is not double counted (tested on a cash identity);
  δ clamp and ROE floor considered; basis flag renamed `consensus_margin_divergence`; one-offs; `normalized_vs_path_gap` non-blocking; ollama_raw
  front-truncation guard; the fade growth convention (open, the operator's D2 ruling); the tax shield after year N; **an unmeasured tax rate is
  unavailable, never a stamped default**; materiality as an interval.
- **22** (controlling Qwen's output): both: change the architecture → the staged design (revision 26); a frozen 12-name benchmark, two masked readers,
  registered metrics, at most 3 iterations then a holdout.
- **23** (the revision-26 build before its first GPU run): items 1-15 built in R26-F; e2e smoke added; paired canary; callable denominators.
- **24** (iteration 1 design questions): A2 (replacement draws, recorded as a post-result amendment) and B2 modified (joint reach, beyond reach
  non-actionable, per-name actionability) → **Amendment 1** (operator approved).
- **25** (sample spread; criterion 4; reader faults): Gemini and ChatGPT replies → **Amendment 2** (coordinator rulings; operator delegated):
  adopted where both agreed (S3, S4, reject S2/S5, code-owned discount rate, criterion 4 rewritten with ChatGPT's durability-thesis wording, ITGR is a
  real failure); on disagreements: terminal return, baseline and long-run margin stay analyst-owned (ChatGPT, against Gemini's defaults which would
  recreate default anchoring); growth label code-derived (Gemini); basis check as an annotation; deterministic memo grounding; path-dominated flag
  (Gemini); freeze rule (iteration 3 last; 0 incoherent and ≥70% coherent → paper run; else paper-only low confidence).

## 3. After cross-check 25
- **ChatGPT architecture note (shared link)**: the v33 charter in every stage → verified, a real defect; `max(r, RONIC)` → already fixed; a
  "revision-28 roadmap" (sensitivity-first, targeted research, typed claims with `unresolved`, decision robustness) recorded.
- **ChatGPT on the charter fix**: do not run iteration 4 "only if iteration 3 fails and pick the better score"; instead one registered defect-correction
  comparison, run regardless, one change only, side by side, no winner on score, stages 2-4 only, freeze anyway → **Amendment 3** (adopted in full,
  with the disclosure that iteration 3's score had been read).
- **Gemini on the KOF context overflow**: count KOF as a scored design failure; first fix = output cap + salvage + recovery turn + correct label
  (adopted, deferred past the freeze); "retry avalanches from the quote verifier" partly wrong on the data (most rejections are the proximity rule).
- **ChatGPT, strategic**: factor-led, AI-supervised design; screener primary; no unconditional AI veto; valuation diagnostic; deterministic exit
  contract; the A→E ladder; validate the deployed model → adopted with five rulings (the contamination rule; deployed model is Q5_K_M not Q4; the
  monitor's real-event recall is 6/20 strictly) → `SPEC_factor_led_v1.md` (draft, not yet cross-checked; predates baseline A).

## 4. Pattern for the next cross-check (if the operator wants one)
Write `CROSS_CHECK_26_strategy_after_baseline_A.md`: background (file 02's evidence table), the three paths, the recommendation (1 + 2), questions
(is a low-turnover factor tilt worth running; what AI rung is most likely to add value and how to test it in a one-year post-cutoff window plus paper;
the hard-stop list; the exit contract; bars to register). Mirror to GitHub, give the operator the link.
