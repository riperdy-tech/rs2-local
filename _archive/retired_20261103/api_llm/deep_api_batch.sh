#!/usr/bin/env bash
# Batch driver for the cloud arm (api_llm/deep_api_run.py).
#
#   bash api_llm/deep_api_batch.sh QUEUE_FILE [CONCURRENCY]
#
# QUEUE_FILE holds one job per line: "TICKER CONSENSUS_DIR" to replay a finished local run,
# or "TICKER --fresh" to run a name the local tier has not done.
#
# WRITE THE QUEUE WITH UNIX LINE ENDINGS. A CRLF file puts a trailing \r on the --dir argument
# and every job dies at the pack read (measured 2026-08-24: all 26 failed instantly). In Python:
# io.open(path, "w", newline="\n").
#
# Concurrency defaults to 3 — the cloud arm calls the LOCAL SearXNG for every search, and the
# local deep sweep may be searching at the same time; 3 streams do not starve it.
set -u
cd "$(dirname "$0")/.."
QUEUE="${1:?usage: deep_api_batch.sh QUEUE_FILE [CONCURRENCY]}"
PAR="${2:-3}"
xargs -a "$QUEUE" -P "$PAR" -L 1 bash -c '
  T=$0; D=$1
  echo "[batch] start $T"
  if [ "$D" = "--fresh" ]; then
    python -u api_llm/deep_api_run.py "$T" --fresh > "api_llm/_deep_api_${T}.log" 2>&1
  else
    python -u api_llm/deep_api_run.py "$T" --dir "$D" > "api_llm/_deep_api_${T}.log" 2>&1
  fi
  echo "[batch] done $T exit=$? $(grep -h "^\[deep-api\] $T:" api_llm/_deep_api_${T}.log)"
'
echo "[batch] ALL DONE"
