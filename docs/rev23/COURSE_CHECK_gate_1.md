ON COURSE

# Course check, gate 1: end of the revision 25 Stage 0.3–0.8 build (2026-10-16)
Advice; the coordinator rules. Read: brief, gate summary, `PHASE_4_AMENDMENTS.md` (AMEND) l. 7505–7715, spec §3–5 and v1.1–v1.2, rs2
`01f742b`/`9ed16fc` by `git show`, file hashes. The sealed file was not opened; the suite was not re-run.

**1. The judge: no move away from Muse.** The path is Muse's declarations; the consensus-scaled revenue is gone (spec §3, §4 l. 69–72); arm C
withholds consensus in pass 1 (AMEND l. 7673). A failed check asks, never rejects: with a reason the value computes and the check stays `fail`
+ `reason_given` (`financial_model_tool.py` l. 2723–2734, `test_rev25_bridge.py` l. 404–416, at `9ed16fc`); K1–K4 never change a label.
**Open:** I found no Stage 1 measure of bridge/K outcomes (`pilot_r25/measures.py`'s "unresolved" counts citations). If "unresolved
contradiction" ends up counting raw `fail`s, the scoring rejects Muse's reasoned choices even though the desk does not.

**2. The role of code: arithmetic and guards.** No company-specific rule found. Generic definitions (K2 "peak" = m_0 − m_tc ≥ τ_m; C4
"structural_growth ⇒ g_S > g_rev or a citation") only draw reasons. No default overrides a declaration: R_N0 = R_0 unless declared (spec
l. 47), κ comes from Muse's `base_cf`, WC intensity is the facts' as in revision 24 (`financial_model_tool.py` l. 2329–2341).

**3. Evidence: about 2026-10-20; first stated date, so not moved, but at risk.** It assumes cross-check 21 within a day and a Stage 1 pass, and
gives no date for the fail branch. **Nothing is built for the book itself:** no name, overlay, publication path or TRK-06 entry in rs2
`9ed16fc`, `stock-screener` `origin/main` or `rev23/` (searched `rn_muse|muse_paper|muse_overlay`), and the summary's "Remaining" has no such
step, so "starts at once" (PLAN v3) cannot happen as written.

**4. Scope: nothing material outside plan v3.** Departures, none ruled as such:
- 0.4's order (labels, then synthetic) ran synthetic first (20:23), labels last (22:46). Harmless.
- PLAN l. 88 "not changed: … working-capital fixes", yet the bridge replaces step 2d's base-normalized WC (spec l. 72, AMEND l. 7532).
  Substance kept (WC on Muse's own revenue path); reconcile in writing.
- The Stage 2 seal, due "now" (PLAN l. 60, HANDOFF step 5), came at 23:50, after the freeze, from the 2026-09-16 list in the dev tree
  `stock-screener/public/data` (branch `claude/minus-two-percent-issue-w94rfr`). rs2's own resolver (`python paths.py`) reads
  `screener-publish/public/data`, list generated 2026-10-15T17:44:03Z. The summary's "the newest" holds only for the stale folder.
- τ_g (K1) entered as a prior in v1.2, outside 0.4's labels → calibrate → held-out sequence.

**5. The kill rule: not triggered** (no Stage 1 result); no disguised second revision: every TASK/desk change (late-horizon rule, Bull/Bear own
m_N `a6a1ec2`, C's pass-1 withholding) precedes any run and sits inside 0.2–0.7. **Residual gap:** v3 routes a failed arm to the model test,
but a "runner defect" fix plus re-run inside Stage 1 is not covered, and the desk now adds ten named reason requests (C1–C5, C1b, K1–K4).
Register now that reason loops, budget exhaustion and unresolved fails are model outcomes, not defects.

**6. Curve-fitting: no value moved after a result; the order claim is overstated.** All ten recorded hashes match today's files; mtimes run
DEFINITIONS 19:54 → README 20:20 → synth 20:23 → protocol 22:45:54 → labels 22:46:43 → gaps 22:46:53 → freeze `4deab98` 22:48:00. The
frozen values equal `01f742b`'s UNCALIBRATED placeholders (20:39), dictated by `BRIEF_R25_0_3` l. 48–49. But:
- **Priors set after exposure.** Placeholders and ranges (20:20) post-date H3 (19:56) and the spec's MU example (20:02). τ_b = 0.01 decides
  that very case: MU's 24% operating vs 22.2% X-basis (gap 0.018) draws C5 at 0.01, silent at ≥ 0.018, inside the admissible 0.0025–0.02
  (README l. 25). No sign of tuning (protocol l. 54 gives a generic reason), but MU's C5 result in Stage 1 is no evidence for τ_b.
- **Labels written 49 s after the protocol** were prepared before it was hashed: "fixed before the labels" (AMEND l. 7628, `bridge_checks.py`
  l. 19) proves file order, not knowledge order. Harmless here: nothing was fitted.
- **The held-out split was not held out:** the 0.3 audit ran all 150 cases into a permanent test (AMEND l. 7597) and the C5 ruling came from
  building the set (l. 7583); step 6 (l. 7649) re-ran known cases. Mechanics only.
- **7 tolerances vs 6 labelled companies, 0 contradictions;** none fitted, so the levels are untested rather than over-fitted.
- **Same names set and judge:** the six revision-24 names were the calibration set and the motivating cases (MU: C5, K2, `a6a1ec2`; MPWR: K1)
  and are 6 of the 8 Stage 1 names. Stage 1 is in-sample for the checks, so a book started on a Stage 1 pass rests partly on in-sample
  evidence. State it in the registration.
- No "defect fix" moved a result (H3 deviation 1 keeps `rejoin_v1`; generator fixes preceded any choice; `1e-12` touches ties only).

**Advice** (owner: coordinator). **Before Stage 1:** (1) define "unresolved" as a fail with no reason, reasons graded blind; (2) register the
failure classes in 5; (3) freeze and hash the Stage 1 rubric file (`pilot_r25/versions.py` stamps whatever file it is given). **Before
cross-check 21:** (4) rule on the Stage 2 pool: re-seal from the resolver's list under a rule fixed before computing, with the nonce inside
the hash (today anyone can recompute the names from AMEND l. 7709), keeping the old hash; or record why 09-16 stands. **Carriable:**
(5) schedule the book's build (name, overlay, `screener-publish`, TRK-06, GPU throughput) as non-GPU work during Stage 1; (6) correct the
record: "held-out" → re-run, "fixed before" → file order, v3 time 20:16 not 22:10 (summary l. 6), τ_b's pivot on MU, the WC "not changed"
line, τ_g untested. Verdict (advice): **APPROVED WITH CONDITIONS.**
