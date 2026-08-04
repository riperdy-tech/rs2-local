#!/usr/bin/env bash
# Definitive post-fix re-run of the full 24-stock set (all fixes: Engine-4 bridge,
# financial routing, pre-profit→Engine4, cyclical→Engine1-DCF, mid-cycle + analyst-
# consensus anchors). Always re-runs (new timestamp dir); 25s sleep between stocks
# to avoid sustained-load Ollama 500s. Fault-tolerant.
cd "C:/Users/riper/Downloads/RS2 Local" || exit 1
SET="MSFT AMD META NFLX TSLA HD PG COST XOM FANG JPM V LLY MRNA CAT DE FCX LIN AMT O NEE CEG PLTR OKLO"
# resume marker: skip any ticker already re-run in this fix-era (report newer than this)
MARK="2026-06-26 23:30:00"   # final-code cutoff: re-run anything older, skip completed-after
for t in $SET; do
  d=$(ls -dt reports/${t}_*/ 2>/dev/null | head -1)
  if [ -n "$d" ] && [ -f "$d/FINAL.md" ] && [ -z "$(find "$d/FINAL.md" ! -newermt "$MARK" 2>/dev/null)" ]; then
    echo "==== $t : already done in fix-era, skip ===="
    continue
  fi
  echo "==== $t : start $(date +%H:%M:%S) ===="
  python run_rs2.py "$t" --no-research || echo "==== $t : FAILED ===="
  echo "==== $t : end $(date +%H:%M:%S) ===="
  sleep 25
done
echo "==== ALL24 DONE ===="
