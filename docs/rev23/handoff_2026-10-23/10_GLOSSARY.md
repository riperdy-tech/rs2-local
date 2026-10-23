# 10. Glossary

- **Coordinator**: the lead AI session (Claude) that designs, rules, audits and reports; builders and readers are subagents.
- **Operator**: the user, who owns the decisions and the money.
- **rs2 / RS2**: the analyst pipeline repository `rs2-local`.
- **MRI**: macro-regime-indicator, the macro engine (anchors, regime, shocks); another Claude session works on it.
- **Dual Door / Door 1 / Door 2 / Door 3**: the screener's nomination paths (quality / value / trend leaders).
- **research_now / watchlist / band hysteresis**: the screener's top group (~50-60), the wider list (~160), and the rules that keep names in until
  they fall clearly out.
- **KIS / KIS_HALT**: the broker connection for real money / its halt switch (on).
- **DEPTH_PAUSED**: file that pauses the production analyst sweep (present).
- **Pack / blind pack**: the data briefing given to the model / with consensus-, price- and reference-derived lines removed.
- **Pack revision**: the version of what the model is told (26 → 27 → 28 in this window).
- **Desk / 25.2**: the DCF engine (`financial_model_tool.py`) / its schema used by revision 26 (explicit 5 years then a fade).
- **X basis / bridge / K_0**: the valuation earnings basis (net income + after-tax acquired amortization) / the conversion from operating margin to it /
  the base-year non-operating dollars held flat.
- **base_cf, owner earnings, kappa (κ)**: the base-year cash flow; κ = base_cf / X_0 scales years 1-5 cash flows (the year-6 defect: the long run is not
  scaled).
- **D2**: the terminal-reinvestment design (explicit reinvestment; O1-O8 approved; not enabled; the fade convention open).
- **Stage 1-4, K = 3, spread**: research, blind forecast (three samples), reveal and crux, memo; spread = (max − min)/median of the three Base values.
- **Crux / reachable / jointly_reachable / beyond_reach / path_dominated**: the judgment inputs the analyst says decide the price; whether the price is
  reachable by one input, by several together, by none; jointly reachable with no single input reaching (the gap is in the years-1-5 path).
- **Data no-call**: a name the data cannot value (base_cf, shares, bridge, family), decided before model time, outside the scoring denominator.
- **Canary**: stage 3 re-run with the consensus shifted ±3 points to measure anchoring (pull).
- **Readers / masked extract / criteria c1-c4**: two blind agents scoring extracts with results removed on facts, forecast-memo consistency, no copy of
  revealed numbers, durability (amended).
- **Iteration**: one design run of stages 2-4 on the frozen stage-1 dossiers (1 non-counting, 2 partial, 3, 4 complete).
- **Amendment 1/2/3**: SPEC §9/§10/§11 (replacements and reach; pack 27 and the freeze rule; the SYSTEM-message comparison).
- **Freeze**: revision 26 at pack revision 28, paper-only, low confidence (2026-10-23).
- **Holdout**: CTVA, NHC, TTAM, CLDT, untouched.
- **Baseline A**: the screener alone, point in time, factor-controlled (no alpha over 2017-2025).
- **Rungs A-E**: the factor-led test ladder (screener; + risk; + AI investigation; + AI forecasts; + valuation).
- **Gate 1 / 1b / 2**: the earlier engine and Muse validation gates (failed / partial / inconclusive).
- **Muse / Glimmer**: an earlier local model family (ruled out 10-17); Glimmer ran the Phase 6 monitor.
- **ollama_raw**: the project's own Ollama raw provider (template rendering + tool-call parsing).
- **SearXNG / LDR / deep_research**: the local metasearch / local-deep-research library / the research script built on it.
- **Three bounds**: the delisting-return treatments (excluded, −100%/10th percentile, last close).
- **Stage P (P1-P5)**: per-name preparation (draw, data, deep research, catalyst brief, blind pack + leak audit).
