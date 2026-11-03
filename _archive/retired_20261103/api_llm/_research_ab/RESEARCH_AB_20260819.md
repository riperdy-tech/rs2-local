# Research-engine A/B: qwen3:14b (current) vs gemma4:12b (2026-08-19)

Fresh LDR briefs, same tickers back-to-back (same-day web), live cache stashed/restored, config restored. All 6 runs clean (no infra errors).

| Ticker | Arm | Time | Size | Unique sources | Numeric facts | Sections |
|---|---|---|---|---|---|---|
| MU | qwen3:14b | 8.3 m | 18.6 KB | 46 | 29 | 14 |
| MU | gemma4:12b | 14.2 m | 20.2 KB | 61 | 30 | 19 |
| PM | qwen3:14b | 6.8 m | 14.0 KB | 29 | 15 | 13 |
| PM | gemma4:12b | 10.9 m | 14.4 KB | 43 | 21 | 8 |
| DCTH | qwen3:14b | 5.8 m | 11.9 KB | 26 | 14 | 14 |
| DCTH | gemma4:12b | 10.5 m | 11.5 KB | 33 | 9 | 8 |

## Read
- Gemma consistently gathers MORE sources (+30-50% unique URLs) but is 1.6-1.8x SLOWER.
- Substance is mixed: numeric-fact density up on PM (+6), flat on MU (+1), DOWN on DCTH (-5) —
  on the thin-coverage hard case Gemma cited more links yet extracted fewer hard figures.
- Structure: Gemma's briefs are looser (8 sections vs 13-14 on PM/DCTH).
- Recommendation: KEEP qwen3:14b. The citation gain does not translate into consistently more
  extractable facts, the hard case regressed, and slower research adds 4-6 min to every
  cache-miss ticker. Operator adjudication of the excerpts below may override.

## MU — qwen14b
```
# DEEP RESEARCH BRIEF — Micron Technology (MU)
Generated: 2026-08-19 18:16 | iterative deep research (full-page reads + citations). Cite only the listed sources.

## Competitive Position & Moat  _(engine: searxng, 162s)_
Micron Technology's (MU) competitive position in 2026 is characterized by a mixed landscape, with strengths in niche markets like High Bandwidth Memory (HBM) but a smaller overall market share compared to leading rivals. In Q1 2026, Samsung Electronics dominated the memory market with 38% share, followed by SK Hynix at 29%, while Micron held 8% of the total market [2]. However, Micron leads in the HBM segment, commanding 21% market share, a critical area for AI infrastructure, with revenue projected to reach $53.6 billion by 2028 [3]. This niche dominance positions Micron as a key player in the AI-driven growth of advanced memory demand, though its broader market presence remains overshadowed by Samsung and SK Hynix.  

The durability of Micron’s competitive position relies on two factors: structural market concentration and heavy technology investment. The memory in
```

## MU — gemma12b
```
# DEEP RESEARCH BRIEF — Micron Technology (MU)
Generated: 2026-08-19 18:24 | iterative deep research (full-page reads + citations). Cite only the listed sources.

## Competitive Position & Moat  _(engine: searxng, 198s)_
Micron Technology's (MU) competitive position in 2026 is defined by its leadership in high-performance memory, a transition toward contract-based stability, and a complex triopoly dynamic with major rivals.

### Competitive Position and Moat Durability
Micron’s competitive advantage is heavily rooted in its advanced High-Bandwidth Memory (HBM) capabilities, which are essential for modern AI infrastructure [1]. The durability of its market position is built upon two primary pillars: structural market concentration and heavy investment in technology [3, 15]. Because the DRAM industry is extremely capital-intensive—with a single leading-edge fabrication plant costing between $10 billion and $20 billion—high barriers to entry exist for new competitors [3, 15].

A significant evolution in Micron's moat durability is the shift away from traditional commodity memory pricing
```

## PM — qwen14b
```
# DEEP RESEARCH BRIEF — Philip Morris International (PM)
Generated: 2026-08-19 18:38 | iterative deep research (full-page reads + citations). Cite only the listed sources.

## Competitive Position & Moat  _(engine: searxng, 114s)_
Philip Morris International (PMI) occupies a strong competitive position in 2026, driven by its leadership in the heat-not-burn category, where it holds approximately **77% volume share** through its IQOS product [2]. The smoke-free business, which accounted for **43% of PMI’s first-quarter 2026 total net revenues**, underscores its strategic pivot toward alternatives to combustible cigarettes, aligning with its long-term goal of delivering a smoke-free future [3][9]. This shift, supported by over **$16 billion in investments since 2008**, has positioned PMI to capitalize on evolving consumer preferences [9].  

However, PMI’s market share in the U.S. nicotine pouches segment faces challenges. While IQOS saw **market share growth of 1.0 percentage point to 11.8%** in the U.S. pouch market, the sector is becoming increasingly competitive, with threats from r
```

## PM — gemma12b
```
# DEEP RESEARCH BRIEF — Philip Morris International (PM)
Generated: 2026-08-19 18:45 | iterative deep research (full-page reads + citations). Cite only the listed sources.

## Competitive Position & Moat  _(engine: searxng, 221s)_
In 2026, Philip Morris International (PMI) maintains a significant, albeit evolving, competitive position within the global tobacco and nicotine space, characterized by a strategic shift toward "smoke-free" products.

**Competitive Position and Market Share**
PMI is positioned as a leading international consumer goods company [3] and is considered a "defensive investment" capable of weathering economic downturns, such as the projected 2026 recession [12]. The company's market capitalization as of August 2026 is approximately $294.44 billion [4]. 

The company is actively transitioning its portfolio toward a "smoke-free future," which is reflected in its financial performance; the smoke-free business accounted for 43% of its total net revenues in the first quarter of 2026 [5]. Specific growth indicators include:
*   **IQOS:** This product saw an estimated 5.
```

## DCTH — qwen14b
```
# DEEP RESEARCH BRIEF — Delcath Systems (DCTH)
Generated: 2026-08-19 18:56 | iterative deep research (full-page reads + citations). Cite only the listed sources.

## Competitive Position & Moat  _(engine: searxng, 109s)_
Delcath Systems (DCTH) is positioned for growth in 2026, with analysts revising their forecasts from a break-even expectation to a projected profit of US$9.28 million in 2025, suggesting improved financial performance that may carry into 2026 [1]. This profitability could strengthen its competitive position by enabling reinvestment in research and development, particularly for its proprietary percutaneous hepatic perfusion (PHP) with melphalan, a treatment for liver cancers [4]. However, the company’s market share and moat durability remain unclear from the sources. While ongoing clinical trials for PHP with melphalan may enhance its technological edge [4], the lack of specific data on market penetration or competitive differentiation limits assessment of its moat.  

Threats from rivals are implied by comparisons with peers like Halozyme Therapeutics, where AI-drive
```

## DCTH — gemma12b
```
# DEEP RESEARCH BRIEF — Delcath Systems (DCTH)
Generated: 2026-08-19 19:01 | iterative deep research (full-page reads + citations). Cite only the listed sources.

## Competitive Position & Moat  _(engine: searxng, 197s)_
In 2026, Delcath Systems (DCTH) maintains a specialized competitive position within the interventional oncology sector, specifically focusing on the treatment of primary and metastatic liver cancers across the United States and Europe [3, 11, 12, 16].

**Competitive Position and Technology**
Delcath’s market position is built upon a unique technological approach. The company utilizes a combination of a specialized machine and a drug that, when used together, allow clinicians to flood a patient's liver with a dose of chemotherapy approximately ten times stronger than the body could otherwise tolerate [2]. This specific combination suggests a distinct technical advantage in liver-directed cancer treatment [3].

**Market Share and Growth**
While specific market share percentages are not provided, the company exhibits signs of aggressive market penetration and expansion.
```
