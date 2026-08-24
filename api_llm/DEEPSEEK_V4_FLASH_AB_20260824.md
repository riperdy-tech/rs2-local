# Local Qwen deep vs DeepSeek V4 flash — 28-ticker parallel run

Date: 2026-08-24 · Arms: local `rs2-analyst-deep` / `-mtp5` (Qwen3.8-27B UD-Q5_K_M) vs `deepseek-v4-flash` via API, `reasoning_effort: high`.

Both arms received the **byte-identical frozen `_pack.md`** each local run had already saved, 3 samples each, the same `search_web` / `fetch_page` tools against the same local SearXNG, the same 12-call research budget, and the same imported plausibility guard and band-direction verdict rule. The local RS2 engine was not modified; the cloud arm is a standalone additive script, `api_llm/deep_api_run.py`, writing only under `api_llm/deep_api/`.

## Headline

| Measure | Value |
|---|---|
| Direction agreement | **22/28 = 79%** |
| Verdicts that differ | 6 — ABNB ADSK AMZN CLS EXEL JKHY |
| Converged runs (spread within 25% tolerance) | cloud 14/28 · local 10/28 |
| Cloud median IV below local | 17/28 |
| Model time | local 50.1h -> cloud 8.8h (5.7x faster) |
| Tool calls | cloud 1155 · local 1164 |
| Cloud spend | $5.00 across 84 samples, 0 truncated, 75 plausible |

## Verdict matrix

| local \ cloud | undervalued | hold | overvalued |
|---|---|---|---|
| **undervalued** | 4 | 1 | 1 |
| **hold** | 0 | 5 | 2 |
| **overvalued** | 0 | 2 | 13 |

## Every ticker

| Ticker | Price | Local | Cloud | Local IV | vs price | Cloud IV | vs price | L spread | C spread | Cost |
|---|---|---|---|---|---|---|---|---|---|---|
| AAPL | $316.83 | overvalued | overvalued | $185.0 | -41.6% | $180.0 | -43.2% | 29.1% | 21.6% | $0.22 |
| **ABNB** | $185.0 | overvalued | hold | $142.0 | -23.2% | $156.0 | -15.7% | 48.0% | 70.5% | $0.22 |
| **ADSK** | $251.29 | undervalued | overvalued | $256.0 | +1.9% | $231.3 | -8.0% | 3.9% | 10.3% | $0.19 |
| AGX | $528.01 | overvalued | overvalued | $185.0 | -65.0% | $274.0 | -48.1% | 142.9% | 64.7% | $0.21 |
| AMD | $464.175 | overvalued | overvalued | $167.5 | -63.9% | $138.0 | -70.3% | 39.3% | - | $0.21 |
| **AMZN** | $265.84 | hold | overvalued | $234.0 | -12.0% | $181.0 | -31.9% | 162.5% | 16.8% | $0.21 |
| ANET | $186.45 | overvalued | overvalued | $128.5 | -31.1% | $78.0 | -58.2% | 64.9% | 40.3% | $0.22 |
| ATI | $215.99 | overvalued | overvalued | $81.0 | -62.5% | $80.4 | -62.8% | - | 30.8% | $0.19 |
| AVGO | $367.88 | overvalued | overvalued | $215.75 | -41.4% | $280.0 | -23.9% | 2.1% | 1.4% | $0.18 |
| AZN | $166.565 | undervalued | undervalued | $207.5 | +24.6% | $188.0 | +12.9% | 12.8% | 9.2% | $0.17 |
| BMRN | $69.33 | undervalued | undervalued | $86.5 | +24.8% | $112.0 | +61.5% | 30.7% | 18.7% | $0.26 |
| CART | $50.67 | undervalued | undervalued | $68.0 | +34.2% | $71.95 | +42.0% | 18.3% | 11.6% | $0.18 |
| CIEN | $399.47 | overvalued | overvalued | $140.0 | -65.0% | $124.5 | -68.8% | 94.7% | 9.2% | $0.18 |
| **CLS** | $301.36 | overvalued | hold | $212.0 | -29.7% | $338.5 | +12.3% | 23.2% | 35.7% | $0.20 |
| CMI | $593.24 | overvalued | overvalued | $460.5 | -22.4% | $425.0 | -28.4% | 9.0% | 23.7% | $0.22 |
| DELL | $437.55 | overvalued | overvalued | $220.0 | -49.7% | $310.0 | -29.2% | 86.5% | 63.6% | $0.24 |
| EMBJ | $77.75 | hold | hold | $69.5 | -10.6% | $82.0 | +5.5% | 26.2% | 30.5% | $0.21 |
| **EXEL** | $53.69 | hold | overvalued | $45.9 | -14.5% | $36.1 | -32.8% | 105.7% | 27.8% | $0.19 |
| FIX | $1672.9399 | overvalued | overvalued | $942.5 | -43.7% | $683.5 | -59.1% | 27.1% | - | $0.14 |
| GD | $386.07 | hold | hold | $422.0 | +9.3% | $403.0 | +4.4% | 24.6% | 10.5% | $0.11 |
| GEV | $966.01 | overvalued | overvalued | $425.0 | -56.0% | $417.0 | -56.8% | 135.8% | 8.7% | $0.11 |
| GMED | $85.67 | hold | hold | $109.0 | +27.2% | $91.0 | +6.2% | 56.0% | 14.3% | $0.10 |
| GOOG | $336.88 | overvalued | overvalued | $295.0 | -12.4% | $269.0 | -20.1% | 36.3% | 70.7% | $0.10 |
| GRDN | $37.93 | overvalued | overvalued | $24.0 | -36.7% | $26.0 | -31.5% | 32.5% | 41.5% | $0.12 |
| INCY | $127.81 | hold | hold | $140.0 | +9.5% | $127.0 | -0.6% | 71.1% | 125.8% | $0.16 |
| **JKHY** | $166.2 | undervalued | hold | $188.0 | +13.1% | $158.8 | -4.5% | 3.8% | 20.4% | $0.21 |
| KFY | $85.06 | undervalued | undervalued | $97.0 | +14.0% | $100.075 | +17.7% | 2.1% | 6.3% | $0.12 |
| PM | $189.93 | hold | hold | $189.0 | -0.5% | $211.0 | +11.1% | 18.6% | 29.0% | $0.11 |

Bold ticker = the two arms reached different verdicts. Bands shown in the chart are the min/max of each arm's plausible samples; the median is the published IV.

## What the comparison can and cannot show

- **Spread is not comparable like-for-like.** The local arm passes fixed seeds (1000, 1001, 1002), so its three samples are one frozen, reproducible realization — rerunning returns the same three reports. DeepSeek does not document a seed parameter, so its three samples are independent draws. Fixed seeds do not narrow the spread; they freeze one particular value of it.

- **Reasoning effort is not the same quantity.** Local runs Qwen at `high`, which the Qwen chat template maps to `xhigh` — Qwen's maximum. DeepSeek's `high` is its own scale and sits one step below its `max`. Comparable in intent, not in budget.

- **Sampling parameters were deliberately not transplanted.** DeepSeek's thinking mode ignores `temperature`, `top_p`, `presence_penalty` and `frequency_penalty` outright, so porting Qwen's 0.6 / 0.95 / 20 profile would have been a silent no-op. Each model ran at its own vendor defaults.

- **Neither arm has been graded against outcomes.** 79% agreement means the two mostly see the same thing. On the six where they part — ADSK is the only full reversal, undervalued vs overvalued on a price sitting between two close IVs — there are two defensible answers and no evidence yet for either. Grading both arms against realized prices is what would settle it.

## Reproduce

```
python api_llm/deep_api_run.py JKHY --dir JKHY_20260824_114148
```

Per-ticker output in `api_llm/deep_api/{TICKER}_{ts}/`: the pack, three reports, three thinking traces, per-sample research snapshots of every query and page fetched, `consensus.json`, `verdict_depth.json`. Nothing is written to `cache/depth_ledger.jsonl`, `depth_overlay.json` or `reports/`.
