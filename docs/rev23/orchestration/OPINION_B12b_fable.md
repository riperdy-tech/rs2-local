# Opinion on B12b (a Fable agent, advice only, 2026-10-30)

Requested by the operator ("check with fable agent for its opinion"). Recorded verbatim in substance; Claude's proposed rulings follow.

**Recommendation:** keep book-ratio δ with K_0 scaled with revenue, but bound it. Close the caveat with a pre-registered
market-target test before E3. Do not revert to O5 as built.

**Reasoning:**
- D2 needs the share of incremental reinvestment funded by debt, ΔD/ΔIC. Under any constant-leverage policy in steady growth
  (a market D/V target, or Debt/EBITDA), debt grows at g, so ΔD/ΔIC = net debt / (net debt + book equity).
- Market weights imply leverage drifting down forever when P/B > 1. The −5 to −10% is the expected P/B-sized bias, not a
  simulator quirk.
- Scaling K_0 is the companion identity: interest grows with debt.

**Danger at the extremes** (census probe):
- δ_book − δ_market: median 0.16, p90 0.65.
- 29 names have δ_book > 0.6, and 18 above 0.8.
- The multiplier δ/(1−δ) exceeds 3× for 11 names: STRW 63×, NGVT 38×, AMT 9.8×.
- The cost of equity is not relevered, so near-zero equity slivers look like free value.

**Negative book equity:** 14 of 95 levered names are refused only by the δ measurement. 10 of them have δ > 1, which is refused
downstream as `input_invalid`, a misnamed code.

**Proposed:**
- (a) Keep δ_book and the scaled K_0.
- (b) Cap δ at 0.75, stamped `delta_book_capped`, and report the value at δ_market as a sensitivity on every levered result.
- (c) Value negative-equity names at the cap, stamped `book_equity_negative`.
- (d) Before E3, pre-register firms that target market D/V, that target Debt/EBITDA, and a buyback-depleted firm.

**Defects:**
- `inputs.py` admits δ > 1, which is refused downstream under a misnamed code.
- K_0 scales every non-operating item with revenue, not just interest.
- RONIC_0 uses tangible capital while δ uses capital including goodwill.
- The PREREG text says "analyst-cited target leverage", but the build uses the filed ratio.
- The test sets the market cap to the true value, so it cannot exercise the market/book divergence.
