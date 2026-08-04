#!/usr/bin/env bash
cd "C:/Users/riper/Downloads/RS2 Local" || exit 1
PY="C:/Program Files/Python312/python.exe"
"$PY" keepawake.py >/dev/null 2>&1 & KA=$!
trap 'kill $KA 2>/dev/null; curl -s -m15 http://localhost:11434/api/generate -d "{\"model\":\"rs2-analyst\",\"keep_alive\":0}" >/dev/null 2>&1' EXIT
for t in JPM PG HD DE FCX V CEG; do
  echo "######## $t : $(date +%H:%M:%S) ########"
  "$PY" run_rs2.py "$t" --no-research --no-enrich 2>&1 | grep -E "backbone|valuation|FINANCIAL|stance|DONE|FAILED|Traceback"
  echo
done
echo "######## TWEAK RE-VALIDATION DONE ########"
