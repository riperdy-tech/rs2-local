#!/usr/bin/env bash
# Batch-run the 24-stock broad-spectrum set through the local RS2 pipeline.
# enrich + deterministic valuation pipeline, NO web research (news doesn't affect
# IV/MoS; keeps the long batch robust). Resumable: skips a ticker that already
# has a FINAL.md. One failure does not stop the batch.
cd "C:/Users/riper/Downloads/RS2 Local" || exit 1

TICKERS="MSFT AMD META NFLX TSLA HD PG COST XOM FANG JPM V LLY MRNA CAT DE FCX LIN AMT O NEE CEG PLTR OKLO"

for t in $TICKERS; do
  if ls reports/${t}_*/FINAL.md >/dev/null 2>&1; then
    echo "==== $t : already done, skip ===="
    continue
  fi
  echo "==== $t : start $(date +%H:%M:%S) ===="
  python run_rs2.py "$t" --no-research || echo "==== $t : FAILED (continuing) ===="
  echo "==== $t : end $(date +%H:%M:%S) ===="
  sleep 25   # let Ollama settle between stocks (avoids sustained-load HTTP 500s)
done
echo "==== BATCH COMPLETE ===="
