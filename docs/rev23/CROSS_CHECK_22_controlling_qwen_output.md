# Cross-check request 22: how do we make a local 27B analyst produce output inside a controllable range, instead of iterating briefing forms by trial and error?

Written 2026-10-19 by the coordinator, at the operator's request. **This is a brainstorm request, not a review of one change.** It is
self-contained. Where an answer would need code you cannot see, say so. Be concrete: we want designs we can build and measure, not general
advice. The coordinator rules on each idea, and the operator decides.

Records (public): `github.com/riperdy-tech/rs2-local`, branch `docs/rev23-records`, folder `docs/rev23/`: cross-checks 20 and 21,
`PLAN_terminal_reinvestment.md` (the end sections hold every result below), `STAGE1_R25_REPORT.md`, `PLAN_phase4_qwen_restoration.md`.

## 1. The system
- **A screener** nominates about 160 US-listed stocks.
- **A local AI analyst** values each one. It reads a briefing ("pack", about 96 KB, roughly 25–30k tokens: filed financial history, defaults,
  consensus, a research summary, population ranges, the task), researches with web-search and page-fetch tools, and calls a **desk** tool
  that does all the DCF arithmetic. Then it writes a long memorandum and a structured contract (JSON).
- **Code computes and gates. The model judges.** Each verdict (undervalued, hold or overvalued) rests on a "crux": the inputs where the
  analyst's view differs from what the price implies, each with verified quotes.
- **Real money will depend on the verdicts.** Trading is halted; everything here is paper and test only.

## 2. The model and its settings
| Item | Setting |
|---|---|
| Model | Qwen 3.8 27B, Q5_K_M (charter v3.3 system prompt), on one RTX 3090 (24 GB) |
| Serving | Ollama, through our own prompt rendering and tool-call parser (`ollama_raw`), because Ollama 0.40.3 dropped nested tool arguments |
| Sampling | temperature 0.6, top-p 0.95, top-k 20, min-p 0; multi-token-prediction speculative decoding (`draft_num_predict` 4) |
| Reasoning | thinking "high"; context 98,304 tokens; about 40 tokens/s; one run per stock takes about 55–95 minutes |
| Runs | one sample per stock (the operator dropped two-runs-per-stock: too slow) |

## 3. What we have observed (every number from recorded runs)
- **Revision 24 (free-form inputs: owner-earnings growth per year plus the long-run inputs), 7 stocks:**
  - 7 of 7 completed; 6 were judged coherent and 1 questionable (one reader, not blind).
  - Every directional call rested on a verified crux.
  - One run's value came out at 1.02× a reference value printed in the pack (copying suspected).
  - Twice the memo contradicted the desk's crux verdict.
- **Revision 25, the long form** (yearly revenue and margin, plus normalization declarations and 10 code cross-checks that refuse the call
  and ask for a reason): MSGE took 127 minutes against 73 on revision 24.
  - 5 of 8 desk calls were refused, and the loop guard fired twice.
  - The model kept failing the same consistency checks.
  - The verdict was coherent in the end.
  - The earlier model (Muse 30B) failed this form outright.
- **Revision 25, the short form** (only the yearly revenue and margin lists; the 10 checks removed), MSGE, TASK and DAC: no loops.
  **A blinded reader judged 2 of 3 incoherent and 1 questionable:**
  - **Copying an anchor:** 2 of 3 copied, almost exactly, a consensus margin for years 1–2 that we printed. That figure was on the wrong
    accounting basis (our defect: it was built from adjusted EPS, 30–48% above filed), and the copy contradicted the run's own stated
    reasoning.
  - **A wrong translation between bases:** "9% after-tax margin corresponds to 13% operating". The pack's own conversion gives about 5%.
  - **Misreading a fact:** a dry-bulk ship rate read as the container rate, and used to label the cycle "peak".
  - **Circular normalization:** "normalized earnings" filled in by copying the desk's own year-5 output.
  - **A wrong summary:** "earlier calls were refused", when two were complete runs with different inputs.
  - **A weak anchor for a perpetual margin:** a 4.7-year contract backlog cited to floor a margin held forever.
- **Pattern so far:** each time we change the form, the model's failures move to wherever the form leaves freedom or where we print a
  number. Blocking checks cause loops. Removing them removes the loops but also the catch.

## 4. What we want
The analyst's outputs inside a **controllable range**:
- reproducible enough that one run per stock is meaningful;
- economically coherent (the numbers it submits match the reasoning it states);
- never anchored on a printed number unless it defends the anchor;
- facts read correctly;
- all without turning the run into a refusal loop, and at about 60–90 minutes per stock on one RTX 3090.

**Constraints:**
- the model must stay local (Qwen 3.8 27B now; a different local model is possible);
- code must do all the arithmetic;
- the AI analyst must stay the judge (the operator ruled that a code-only valuation is a baseline, not the system);
- every change to what the model is told is versioned.

## 5. Ideas we have not tried (critique, rank, or replace them)
1. **Split the run into stages, each with a narrow output:**
   - (a) **fact extraction:** code-generated questions, such as "which line is the container time-charter rate?", answered with quotes
     and verified by code;
   - (b) **judgment:** the analyst chooses from bounded menus (cycle position, margin direction, persistence) with a cited reason;
   - (c) **code builds the numerical path** from those choices and the filed history;
   - (d) **the analyst may override,** with a stated reason and evidence, within a bounded band.
2. **Constrained decoding / JSON schema** for the desk call and contract: grammar-forced structure, enums and numeric ranges.
3. **Remove anchors:**
   - never print a number the model might copy (consensus margins, reference values);
   - expose consensus only through a tool, after the analyst has committed its own view, then require it to reconcile.
4. **Self-consistency by sampling:**
   - N shorter, cheaper samples per decision point (for example the path only), taking the median and the spread;
   - or one long run plus a cheap second "critic" pass by the same model with a checklist.
5. **A separate verifier pass,** by the same model or a small model, with narrow yes/no questions after the memo ("does year 5 match the
   stated normalized earnings?"). Its answers become annotations, never refusals.
6. **Few-shot exemplars:** one or two fully worked, correct desk calls for a cyclical and a steady company, in the pack.
7. **Sampling changes:** lower the temperature (0.2–0.3) for the desk-call and contract turns only; keep 0.6 for research.
8. **A shorter pack:** move rarely used sections behind a retrieval tool, to reduce attention spread over about 96 KB.
9. **Code-owned bases:** the model states margins only on the basis it reads directly (the operating margin), and code converts to the
   after-tax basis with the filed relationship, removing the translation error.
10. **Accept variance and manage it:** report a range across two or three cheap path samples, and size the decision on the range.

## 6. Questions
1. **The architecture:** is one long agentic run, with free-form judgment then a structured desk call, the right shape for a 27B local
   model? Would you split it into stages (idea 1)? Which split gives the most control for the least loss of real judgment?
2. **Bounding numbers without anchoring:**
   - How do we give the model ranges (history, peers, consensus) without it copying them?
   - Is "commit first, then reveal and reconcile" (idea 3) sound?
   - What evidence would show anchoring is gone?
3. **Catching inconsistency without loops:** which inconsistencies should code catch and annotate, which should trigger exactly one
   bounded revision turn, and which should block? Is there a design where one revision turn is allowed but no loop can form?
4. **Fact errors** (misread rates, wrong base translation): which tools or structures prevent them? Code-verified extraction? Quotes
   required for every number used?
5. **Reproducibility:** what sampling settings and protocol make one run per stock trustworthy, or is one run inherently insufficient? If
   sampling is needed, what is the cheapest scheme that gives a usable spread?
6. **Evaluation:** how should we measure "controllable range" so we stop trial and error? We have a blind coherence read (one reader) and
   rule checks. What metric set, sample size and registered stopping rule would let us decide between designs in 2–3 iterations, not 10?
7. **The model:** is a 27B dense model at Q5 the limit here? Would a different local model, a larger quantization, or a non-thinking mode
   for the structured turns change the picture? What would you test first?
8. **What you would do** in our place with about 2 weeks and one GPU.

At the end, give:
- your recommended design in 5 lines;
- the first experiment, with its pass/fail rule;
- the failure mode you think we are most underestimating.
