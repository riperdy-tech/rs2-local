# 11. Prompt templates used for subagents (copy and adapt)

## 1. Blind reader (one per reader, fresh agent each time; two readers per iteration)
Copy the masked extracts and the rubric into a private folder per reader first:
```bash
S=<a scratch dir>; for r in A B; do mkdir -p $S/readers_itN_$r && cp pilot_r25/masked_p4r26/N/*.md pilot_r25/READER_RUBRIC.md $S/readers_itN_$r/; done
```
Prompt (general-purpose agent, background):
> You are a reader in a blind review of equity analyses. You have been given a folder of masked extracts, one text file per company, and a rubric
> (READER_RUBRIC.md). Folder: <path>. Read the rubric first, then each extract in the folder (<tickers>). Score every company on the rubric's four
> criteria, each as coherent, questionable or incoherent, with the exact words from the extract that support each score. Work from the extracts alone:
> do not search the web, do not open any file outside that folder, and do not try to recover anything that was removed from an extract. If you find
> yourself able to tell what a removed number was, say so in the note of the affected criterion and score as if you did not know. You are one of two
> readers. You will not see the other reader's scores. Score each company independently of the others. When done, write the JSON object the rubric
> describes (one entry per extract file, keyed by its ticker, "reader": "<A|B>") to the file reader_<A|B>.json inside that same folder, and return only
> that JSON object as your final answer.

Then copy `reader_A.json`, `reader_B.json` to `pilot_r25/runs_p4r26/N/readers/`, list disagreements, write `adjudication.json`
(`{"names": {"<T>": {"<criterion>": {"rating": "...", "reason": "..."}}}}`) with the iteration-3 standard (a specific, checkable contradiction →
questionable; a weaker objection overruled), then run `score_p4r26.py N`.

## 2. Builder (code)
Always include: read `C:\Users\riper\stocks\AGENTS.md` (and the repo's AGENTS.md); the exact worktree and the files it may create or edit, and the files
it must NOT touch (if the coordinator edits others in parallel); no GPU / Ollama / network unless needed; do not commit or push (the coordinator
audits and commits); tests to run with the exact interpreter; a report format (what was built, test results, ambiguities, a size limit). Examples in
the transcript: "Build S3 spread attribution" (new module + tests, demonstration on real data), "Harden the reader masker".

## 3. Measurement agent (read-only)
"This is a READ-ONLY measurement. Do not edit any repository file; write only in your own scratch folder. No GPU... First confirm you reproduce each
stored value within $0.01; if not, stop and report." (Used for the offline engine measurement; it reproduced all values exactly.)

## 4. GPU probe agent
Include: check `ollama ps` / `nvidia-smi` first and wait if another model holds the card; cap GPU time; unload the model at the end
(`ollama stop <tag>`); call through the project's provider or `/api/chat` with a fresh conversation per question. (Used for the Qwen cutoff probe.)

## 5. After any agent
Audit before reporting: read the diff, recompute one or two key numbers from its data files, check for look-ahead. Agents may hit the API rate limit
and stop; resume them with SendMessage after the reset. Agents may be unable to write report files; save their text yourself.
