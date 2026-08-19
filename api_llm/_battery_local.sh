#!/bin/bash
# Local-Ollama A/B battery (Qwen3.8 evaluation, 2026-08-17): SEQUENTIAL — the local
# server is single-slot (OLLAMA_NUM_PARALLEL=1), so concurrency would put queue wait
# into per-ticker wall times. Usage:  ./_battery_local.sh <ARM_LABEL> [tickers...]
# ARM_LABEL is recorded per row (e.g. flash-api, 38-api-default, 38-api-low).
# Assumes api_llm/config.json already points at the arm's model.
cd "$(dirname "$0")/.."
ARM="${1:?usage: _battery_local.sh <ARM_LABEL> [tickers...]}"
shift
TICKERS="${@:-EXEL HG CAT MU META PM SAP KRYS DCTH}"
TIMES=api_llm/_battery_times_local.csv
[ -f "$TIMES" ] || echo "arm,ticker,start_epoch,end_epoch,secs,exit" > "$TIMES"
for t in $TICKERS; do
  s=$(date +%s)
  # --no-router: the retry router would otherwise reuse stages from a SAME-TICKER audit-failed
  # dir of a DIFFERENT arm (cross-contaminated flash-HG 2026-08-18) — every arm runs full.
  RS2_TICKER=$t python run_rs2.py "$t" --api --no-research --no-router > "api_llm/_battery_${ARM}_$t.log" 2>&1
  rc=$?
  e=$(date +%s)
  echo "$ARM,$t,$s,$e,$((e-s)),$rc" >> "$TIMES"
  echo "[battery:$ARM] $t done rc=$rc in $(( (e-s)/60 ))m$(( (e-s)%60 ))s"
done
echo "[battery:$ARM] DONE"
