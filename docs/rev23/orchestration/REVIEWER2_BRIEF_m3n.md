# Reviewer 2 brief: 3N event truth labels (blind)

You are an independent reviewer of SEC filings. You label whether a material event occurred. You do **not** see any AI model's analysis of these companies, nor the other reviewer's labels. Do not look for them.

For each case folder you are given (under `C:\Users\riper\stocks\stocks-workspace\scratch\rev23\m3n\review\`), read:
- `case.json`: the issuer, the class asked about, the candidate filing, its acceptance time and T;
- the filing texts in the folder (plain text extracted from SEC EDGAR primary documents).

Label each case only from those texts. Use no other source and no memory of the company. The rules below are the only definitions.

## Labels

| Label | When |
|---|---|
| `confirmed_critical` | The texts show the event of the asked class, per the class rule below, for this issuer, at or before T |
| `confirmed_noncritical` | A real event of that kind, but one the class's non-critical rule covers |
| `non_event` | (Controls only.) The listed filings cover the whole window, and none shows an event of the class |
| `unknown` | The texts are incomplete, the issuer identity is unclear, or the dates are unclear |
| `insufficient_evidence` | The texts contradict each other, or the cited passage is not in them |

## Class rules

These are copied from `PREREG_m3n.json`. If this brief and that file disagree, the file wins.

| Class | Critical rule | Non-critical rule |
|---|---|---|
| **C1 bankruptcy** | The company (or the listed parent) filed for, or was placed in, bankruptcy, court restructuring or receivership | Only a non-material subsidiary filed, as stated |
| **C2 going concern** | A periodic report states that substantial doubt EXISTS about the ability to continue as a going concern, AND the preceding periodic report (also given) did not state it | "could raise substantial doubt" (conditional), doubt "alleviated", or already stated in the preceding report |
| **C3 restatement** | Item 4.02 non-reliance, or a statement that prior financial statements should no longer be relied upon or will be restated | An immaterial revision |
| **C4 delisting** | An Item 3.01 notice of delisting, or of failing a continued-listing rule, or a suspension or delisting determination | A voluntary transfer of listing; voluntary delisting after a completed merger |
| **C5 company acquired** | The company signed a definitive agreement to be acquired (it is the target), or such an acquisition completed | The company is the buyer; a non-binding proposal; the sale of a subsidiary or of assets |
| **C6 contract loss** | A material definitive agreement, or a major customer, supplier or licence, was terminated or lost | A credit facility ended on refinancing; a scheduled expiry; a merger agreement ended where the company was the buyer |
| **C7 guidance withdrawal** | Previously issued guidance or outlook was withdrawn or suspended | A cut or narrowing that stays in force |
| **C8 debt default / acceleration** | Item 2.04, or a stated event of default, notice of default or acceleration, a missed payment beyond grace, or forbearance because of a default | A covenant amendment or waiver before any default; a cross-default clause merely described |

## Reply

Reply with one JSON line per case:

```json
{"case_id": "...", "label": "...", "quote": "<verbatim passage from a given text, or empty>", "file": "<file name the quote is in>", "event_date_as_printed": "...", "reason": "<one or two sentences>"}
```

The quote must be copied exactly. If you cannot quote it, the label cannot be `confirmed_*`.
