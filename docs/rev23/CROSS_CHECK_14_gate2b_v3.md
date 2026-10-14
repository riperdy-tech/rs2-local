# Cross-check request 14: gate 2b v3, a faster untouched test of engine v2. What is wrong?

**Read:** `REGISTRATION_gate2b.md`, its "v3" section at the top and the "Amendment AK.37 v2" in section 3; SPEC_rebuild addenda AK.35,
AK.37–AK.43, AK.50–AK.53.

**The situation.**
- **Gate 2 found** that Muse forecasts next-quarter revenue growth better than the code engine. That held in every sensitivity, including
  without 53 leaked rows. It found no skill on margin.
- **The registered S5 rule gives Muse weight 0,** because only 143 eligible annual pairs exist against a minimum of 150. So the system
  under test (SYSTEM) is **engine v2 alone**, a code engine without a knowledge cutoff.
- **The operator needs a verdict by the end of October 2026.** v2 waited for 2026-10-30 data and scored annual outcomes in April 2027.
- **v3:**
  - tests engine v2 on **2026-07-31**, which is untouched by engine v2, with gate 2's 2026-06-30 sample excluded because the coordinator
    has seen those companies' June-quarter outcomes in aggregate;
  - covers **every eligible company** (a census);
  - scores the **next quarterly result not public at T** (q1, same-filing measures, results public through SEC Item 2.02 or the pack
    excluded);
  - uses bars **B2** (beat the persistence and population-median run-rates) and **B3** (beat the old engine v1);
  - moves annual calibration (B4) to a real-money condition in spring 2027;
  - adds confirmation dates 2026-08-31, 09-30 and 10-30, scored later and pooled, which never rescue a fail.

Critique freely; the coordinator decides. Rank problems by how much they could make a real-money decision wrong. Where a claim depends on
code you cannot see, say so.

## Questions
1. Is 2026-07-31 truly untouched for engine v2? Is excluding gate 2's 2026-06-30 sample enough, given that the coordinator saw
   gate 2's aggregate statistics (code arm, run-rate arms) on nearby dates?
2. A single date is one market regime. Is a census at one date, with company-clustered intervals, an adequate basis for paper (shadow)
   operation, with the confirmation dates to follow? What could make a one-date pass misleading?
3. q1 scoring of an annual forecast, with the shared mismatch, is gate 2's G1 convention. Is it adequate as the primary target for engine
   v2, whose value rests mainly on years 1–3 and beyond? What would you add, as a reported diagnostic, without moving the bars?
4. At 2026-07-31 many companies had already released the June quarter, and those are excluded. The eligible set is therefore tilted toward
   later reporters (smaller and slower). Does that selection bias the comparison between engines? How should it be reported?
5. Is "B4 as a real-money condition, not a paper condition" sound? Anything else that must be true before real money that this design
   does not test?
6. Anything in v3 that a reviewer would see as fitting the test to the deadline rather than to the question?

At the end, give: the single most important change before the 07-31 run is frozen; and whether v3 can proceed as written.
