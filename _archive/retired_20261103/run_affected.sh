#!/usr/bin/env bash
# Re-run only the stocks whose engine/classification logic changed under the 3 fixes:
# Engine-2 cyclicals (tighter mid-cycle band), option-led/pre-profit (Engine-4 bridge),
# REIT routing. Engine-1 quality names + already-fixed JPM/V are unchanged → skipped.
# The repo root, derived: these helpers live at it, so a folder move needs no edit.
cd "$(cd "$(dirname "$0")" && pwd)" || exit 1
AFFECTED="CAT XOM FANG DE FCX LIN CEG NEE AMT O AMD TSLA PLTR OKLO MRNA"
for t in $AFFECTED; do
  echo "==== $t : start $(date +%H:%M:%S) ===="
  python run_rs2.py "$t" --no-research || echo "==== $t : FAILED ===="
  echo "==== $t : end $(date +%H:%M:%S) ===="
done
echo "==== AFFECTED DONE ===="
