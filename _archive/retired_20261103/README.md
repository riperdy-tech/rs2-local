# Retired 2026-11-03

Moved here in the post-review cleanup (stocks-workspace `docs/review_2026-11-03/B_rs2_local.md` §5.2, STATE.md plan A.4).
Nothing in the live code, the tests or an enabled scheduled task referenced them on that date (`git grep`, task list).

- `run_affected.sh`, `run_all24.sh`, `run_batch.sh`, `run_valbatch.sh`, `validate_batch.sh`, `proof_tweaks.sh`: shell
  drivers of the retired `run_rs2.py` pipeline (itself in `../retired_20260920/`).
- `publish_reports.py`: the old report publisher of that pipeline.
- `keepawake.py`: used only by `validate_batch.sh` and `proof_tweaks.sh`.

History, not a fallback.
