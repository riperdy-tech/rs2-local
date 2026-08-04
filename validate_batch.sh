#!/usr/bin/env bash
# Part 0 validation batch — REWRITTEN for the 12GB-RAM / 24GB-VRAM box.
# Safety design (the old version overflowed the machine):
#   * single-instance lock     -> no two batches at once
#   * orphan pre-kill          -> stale run_rs2/deep_research from prior teardowns die first
#   * PHASE SEPARATION          -> all deep-research (rs2-research) first, UNLOAD, then all
#                                  RS2 stages (rs2-analyst). Only ONE ~23GB model class is
#                                  ever resident -> no swap thrash, no spill into 12GB RAM.
#   * exit trap                -> kill our children + unload models on any exit/interrupt.
# Resumable: research is cached per ticker; FINAL.md newer than the marker = ticker done.
set -u
cd "C:/Users/riper/Downloads/RS2 Local" || exit 1
SET="NVDA GOOG GEV MSFT AMD META NFLX TSLA HD PG COST XOM FANG JPM V LLY MRNA CAT DE FCX LIN AMT O NEE CEG PLTR OKLO"
PY="C:/Program Files/Python312/python.exe"
RV="C:/Users/riper/Downloads/RS2 Local/research-venv/Scripts/python.exe"
MARK=cache/_val_start
LOCK=cache/validate.lock

mkdir -p cache reports
# --- single-instance lock -------------------------------------------------
if ! mkdir "$LOCK" 2>/dev/null; then
  echo "ANOTHER validate_batch is running (lock $LOCK). Exit."; exit 3
fi
# --- kill any orphan pipeline procs from prior teardowns ------------------
powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { \$_.CommandLine -match 'run_rs2.py|deep_research.py' } | ForEach-Object { Write-Output ('kill orphan '+\$_.ProcessId); Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" 2>/dev/null

unload(){ curl -s -m20 http://localhost:11434/api/generate -d "{\"model\":\"$1\",\"keep_alive\":0}" >/dev/null 2>&1; }
# keep the whole machine awake for the batch (Modern-Standby teardown guard)
"$PY" keepawake.py >/dev/null 2>&1 & KA=$!
cleanup(){
  echo "== cleanup =="
  kill "$KA" 2>/dev/null
  powershell.exe -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name='python.exe'\" | Where-Object { \$_.CommandLine -match 'run_rs2.py|deep_research.py' } | ForEach-Object { Stop-Process -Id \$_.ProcessId -Force -ErrorAction SilentlyContinue }" 2>/dev/null
  unload rs2-research; unload rs2-analyst
  rmdir "$LOCK" 2>/dev/null
}
trap cleanup EXIT INT TERM

[ -f "$MARK" ] || touch "$MARK"

# ── PHASE 1: deep research (rs2-research only) ───────────────────────────
echo "#### PHASE 1: deep research ($(date +%H:%M:%S)) ####"
for t in $SET; do
  if [ -f "research/${t}.md" ]; then echo "research $t cached"; continue; fi
  echo "== research $t : $(date +%H:%M:%S) =="
  "$RV" deep_research.py "$t" || echo "== research $t FAILED =="
  sleep 5
done
unload rs2-research; sleep 3
echo "#### PHASE 1 done ($(date +%H:%M:%S)) ####"

# ── PHASE 2: RS2 stages (rs2-analyst only, research cached) ───────────────
echo "#### PHASE 2: RS2 analysis ($(date +%H:%M:%S)) ####"
for t in $SET; do
  d=$(ls -dt reports/${t}_*/ 2>/dev/null | head -1)
  if [ -n "$d" ] && [ -f "$d/FINAL.md" ] && [ "$d/FINAL.md" -nt "$MARK" ]; then
    echo "rs2 $t done (skip)"; continue
  fi
  echo "== rs2 $t : $(date +%H:%M:%S) =="
  "$PY" run_rs2.py "$t" --no-research --no-enrich || echo "== rs2 $t FAILED =="
  sleep 20
done
echo "#### VALIDATION BATCH DONE ($(date +%H:%M:%S)) ####"
