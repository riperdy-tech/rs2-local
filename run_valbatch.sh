#!/usr/bin/env bash
cd "C:/Users/riper/Downloads/RS2 Local" || exit 1
SET="MSFT AMD META NFLX TSLA HD PG COST XOM FANG JPM V LLY MRNA CAT DE FCX LIN AMT O NEE CEG PLTR OKLO"
MARK="2026-06-26 23:35:00"
for t in $SET; do
  vs=$(ls -t reports/${t}_*/val_summary.json 2>/dev/null | head -1)
  if [ -n "$vs" ] && [ -z "$(find "$vs" ! -newermt "$MARK" 2>/dev/null)" ]; then echo "skip $t (val done)"; continue; fi
  echo "==== $t ===="
  python run_rs2.py "$t" --no-research --valonly || echo "$t FAILED"
  sleep 20
done
echo "==== VALBATCH DONE ===="
