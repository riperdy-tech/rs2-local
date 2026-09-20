#!/bin/bash
# DeepSeek v4-pro battery: 3 concurrent (API mode = no GPU contention), per-ticker time log.
cd "$(dirname "$0")/.."
TICKERS="EXEL HG CAT MU META PM SAP KRYS DCTH"
TIMES=api_llm/_battery_times.csv
echo "ticker,start_epoch,end_epoch,exit" > "$TIMES"
run_one() {
  t=$1
  s=$(date +%s)
  RS2_TICKER=$t python run_rs2.py "$t" --api --no-research > "api_llm/_battery_$t.log" 2>&1
  rc=$?
  e=$(date +%s)
  echo "$t,$s,$e,$rc" >> "$TIMES"
  echo "[battery] $t done rc=$rc in $(( (e-s)/60 ))m"
}
N=0
for t in $TICKERS; do
  run_one "$t" &
  N=$((N+1))
  if [ $((N % 3)) -eq 0 ]; then wait; fi
done
wait
echo "[battery] ALL DONE"
