# AUDIT_M5: the first live run (MA smoke) and its fixes (2026-10-29)

## The smoke run

**Run** `MA_20261029T022848Z_87008c0d70a7_1`, with prompt **m3m.prompt.v1**, code `70e3eee`, Ollama 0.40.6, tag
`rs2-analyst-deep-mtp5-v33`, `num_ctx` 98,304, `num_predict` 12,288, think "medium".

- **Status `complete`.** 6 of 6 applicable tasks are `ok` on the first attempt; `thesis_change` is
  `not_applicable_no_prior`.
- **Timings:** 86–182 s per task, about 12 minutes in all. `done_reason` is `stop` everywhere, so none was cut at
  `num_predict`.
- **`prompt_eval_count`** is 31,380–31,467 on every task. Ollama re-evaluated the whole prompt each time (no
  cache-reduced counts), so the post-call overflow check is meaningful. The packet is 129,426 bytes, about 4.1
  characters per token, so the 2.5 preflight estimate is conservative.
- **Claims:** 66, of which **39 `supported`**.

## Reading the 27 unsupported claims

Claude read each one against the cited text.

| Cause | Verdict | Action |
|---|---|---|
| A date in the claim ("June 30, 2026") made its day and year figures to list | **Check too strict** | Fixed: the day and year of a date that a cited item prints are exempt |
| Statement tables print "$ 11,291", and a bare "11,291" did not match | **Check too strict** | Fixed: a wanted figure with no currency matches a printed one; a wanted currency and every unit must still be equal. A currency word ("dollars") now counts as the currency |
| The claim writes "$19,476 million" where the table prints "$19,476" (in millions) | **Real**: the scale-error form the rule exists for | Kept strict. Prompt v2 adds the explicit example: "$19,476 (table in millions)", never "$19,476 million" |
| A listed figure is stripped of the unit the item prints ("17.6" where the item prints "$17.6 billion"), or gains a "$" the item does not print ("$13,315") | **Real** model deviation | Kept |
| Quotes altered: " changed to ', or words changed | **Real** model deviation | Kept |

Rechecking the v1 replies offline under the fixed contract gives **43 of 66 supported**. Every remaining failure is one
of the real kinds above.

**Tests:** 263 pass. The new tests cover a printed date, a date no item prints, a currency word against EUR, and scale
drift.

**The model's substance was spot-read, not scored:**
- business-model claims quote Item 1 verbatim;
- the financial-health figures match F1/F3;
- the risks cite Item 1A.

Scoring accuracy is 3N.

## Prompt version

v1 was used by this one run only. v2 changes one sentence of FIGURES, and the v1 and v2 pin sets are both kept in
`test_tasks.py`.

**Next:** the M-LIVE batch on v2. It runs MA twice for repeatability, then CMRE, HRTG, ILMN and ECPG.
