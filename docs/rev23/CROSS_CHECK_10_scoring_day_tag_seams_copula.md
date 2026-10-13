# Cross-check request 10: before gate 2 is scored. Revenue tag seams in the outcomes, the scoring order, the v2.1 copula. What is wrong?

You reviewed cross-check 9 and the v2 drafts that followed. Your rulings are in SPEC_rebuild AK.19–AK.23, and the operator approved the
results. This request covers what has happened since. **No gate-2 outcome has been read.** Gate-2 run 2 finished at 600 of 600. The masked
control is running, and scoring runs automatically when it ends, probably 10-14 around 05:00–07:00 KST. Anything that should change how the
outcomes are measured must be settled before the coordinator reads the score.

Critique freely; the coordinator decides. A list of problems ranked by how much they could hurt a real-money decision is more useful than
agreement. Where a claim rests on code you cannot see, say so rather than assume.

**Documents:**
- `SPEC_rebuild.md`, addenda AK.19–AK.28 and AL.4–AL.7
- `PROBLEM_REPORT_revenue_tag_seams.md` (fork 2)
- `REGISTRATION_engine_v2_1_copula.md` (draft)
- `REGISTRATION_gate2_DRAFT.md` (the gate-2 bars as registered)
- the D-T1 evidence: `evidence/engine_v2_audit/`

## 1. Revenue tag seams: the outcome measurement (most urgent)

**The defect** (fork 2's AL.6, AL.7 and the problem report):
- **How the extractor works:** the point-in-time extractor (`pit_data`, which is also the screener's production code) chooses a revenue
  XBRL tag for each period separately, from every filing before the cut. A company that files both `Revenues` and
  `RevenueFromContractWithCustomerExcludingAssessedTax` can therefore have consecutive periods on different tags.
- **Two failure modes:**
  - (a) a join between two tags. CIK 1042893: FY2017 455.5M on `Revenues`, FY2018 337.5M on the contract tag. That reads as −25.9%;
    its own 10-K gives −15.6%.
  - (b) a tag that is only a partial line in one year. The case first cited, CIK 1720446, was **withdrawn** after fork 2's hand check
    (AL.9): it was an RMB filer's USD convenience translation, mixed across units by fork 2's measuring script. No hand-checked case of (b)
    exists yet; the AK.28 rule for it stays as a safeguard.
- **Its size** (corrected after the hand check, AL.9): in the $300M+ sample, the extracted annual growth differs from the filing's own
  comparative growth by more than 5 pt in 0.47% of consecutive-year pairs, and by more than 20 pt in 0.38%. 4 of 5 cases were confirmed
  against the filed statements. The worst cases are +1,544% against +8%, and −52% against
  +69%. It is not a look-ahead leak.

**Where it reaches gate 2:**
- **The hard bar G1** scores next-quarter revenue growth and margin change, built as the q1 quarter against the quarter a year earlier.
  Each quarter's tag is chosen separately, so q1 is exposed. (The coordinator first said q1 was safe, in AK.26, and corrected this in
  AK.27.)
- **The fiscal-year-1 annual target** (reported now; primary later for S5's fit and gate 2b) is exposed the same way.
- **The inputs** Muse and the code saw (priors, growth features) are exposed too. They are frozen for gate 2.

**Registered before any outcome is read (AK.27, AK.28):**
- **The tag-consistent outcome.** Growth and margin change come from the q1 filing's own comparative columns: one accession, so the two
  quarters cannot be on different tags. Where the q1 quarter is a derived Q4 (fiscal year minus nine months), both legs use one tag present
  in both filings. The annual target uses the year-1 10-K's comparative column for year 0.
- **A partial line inside one filing** (failure b): where a filing carries more than one revenue tag for both periods, the tag with the
  largest current-period value is used, on the reasoning that a total is never smaller than a line within it. The comparison is made only
  within one unit (the outcome's currency), because a convenience translation in another unit would otherwise win or lose by the exchange
  rate (AK.29). How often the tags disagree
  by more than 1 pt is reported.
- **Audit 1** reports every bar both ways, registered and tag-consistent, with the count of rows that differ.
- **Which version governs:** the operator has ruled, before any score exists, that the **tag-consistent outcome governs** (AK.30). The
  registered version is reported beside it. Question 3 now asks whether that ruling is sound, and what it could miss.

**Questions:**
1. Is the same-filing comparative the right correction for an outcome? Can it still mis-measure: restated comparatives, a 10-Q/A,
   changes in segment presentation, a derived Q4 across two filings?
2. Is "largest current-period value among the tags present for both periods" a sound rule for failure (b)? It is not a total-revenue
   closure test (the report's F3). Where can it pick wrongly: gross versus net, pass-through revenue, excise taxes?
3. Should the tag-consistent version govern? The registered definition is the extractor's output. Changing it before reading outcomes is
   allowed by the project's rules, but it is a change.
4. Gate 2's **inputs** were built by the same extractor. Is gate 2 still interpretable? The proposed treatment is to keep the frozen
   inputs and report the share of company-dates with a seam in their input history as a stated limitation. Is that enough?

## 2. What the gate-2 verdict will and will not mean

The gate-2 registration has four hard bars: G1 forecast skill, G2 direction, G4 anchoring and G5 integrity.

**G4 does not depend on any outcome, so it is already known.** Of the red team's proposed revisions, 18 of 85 (21%) move toward the
market price without new evidence. The bar allows 10%. Counting only a new quote as evidence (G4-strict), it is 26 of 85. The code refused
all of them (0 accepted). So the registered gate-2 verdict will almost certainly be **FAIL**, whatever G1 shows.

**What decides the next step** is the pre-registered branch rule (AD.5), read from the diagnostics:
- **C1:** pass 1 beats all three baselines (R3a);
- **C2:** pass 1 beats the code only;
- **C3:** Muse fails, or its behaviour is unusable.
- **In every branch:** the red team stays only if it beats pass 1 (R3b), and multi-sampling is required if R8 says so.

**Questions:**
5. Is it right that a G4 failure, a red-team anchoring behaviour the code already refuses, makes gate 2 FAIL while the branch rule still
   routes the work? Or should a G4 failure decide the branch by itself, as "behaviour unusable" (C3)?
6. Anything in how the masked control (G6) or the repeat control (R8) should be read that is not already registered?

## 3. Scoring before the repeat control (AK.25)

On the operator's approval, scoring now runs straight after the masked control, and the repeat control runs afterwards.
- **Why this is safe:** R8 is a reported diagnostic, not a bar. It reads no outcome, and it runs from the frozen worktree on
  hash-verified copies with its own freeze.
- **The unattended chain:** a scheduled task runs the steps (data refresh, score, register the repeat control) and reports nothing. The
  coordinator audits before any number is reported: an independent recomputation, Audit 1, and a hand check of 20 outcomes against
  the SEC filings.

**Question:**
7. Any way the reorder, or the automation, could bias or corrupt the result?

## 4. The v2.1 copula registration (draft)

The tail test D-T1 triggered: same-year revenue and margin residuals fall together 1.6–1.9× as often as the Gaussian copula draws. A
t(ν=4) copula was tested and withdrawn: it under-fits that pair and over-widens others (AK.20).

**The draft proposes the checkerboard empirical copula of the six-dimensional residual rank vectors:**
- only complete vectors, at least 500 per family;
- the marginals untouched;
- built at vintage V and tested on the untouched residuals of V+1.

**Its tests and bars:**
- **C1:** both tails, all 18 pairs, with ratios in 0.67–1.5 and a better mean log ratio than v2.0;
- **C2:** the energy score, with a paired bound;
- **C3:** E3/E4 invariance within ±0.5 pt;
- **C4:** E5 re-run;
- **C5:** the effect on the value level, reported.

A pass makes it a candidate only.

**Questions:**
8. Is the empirical copula the right candidate? Consider the survival selection of complete vectors, the ties, and the six dimensions
   with about 1,100 financial vectors.
9. Are C1's per-pair bars (0.67–1.5 on pooled test rates) powered enough to fail a wrong copula without failing a right one by noise? The
   financial pairs have about 1,000 test rows. Is the energy score (C2) the right proper score for a six-dimensional copula, or is it
   known to be insensitive to dependence?
10. Anything missing from the AL.5 conditions?

## 5. At the end, please give

1. The single change most needed before the coordinator reads the gate-2 score.
2. Your ruling on question 3: tag-consistent or registered.
3. Whether the v2.1 registration can be approved as written, and if not, the exact changes.
