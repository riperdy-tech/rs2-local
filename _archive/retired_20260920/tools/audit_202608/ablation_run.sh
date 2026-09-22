#!/usr/bin/env bash
# Stage-ablation A/B (audit 2026-08 deferred experiment): do S2 (quality) and S6 (red team)
# earn their ~21% of per-ticker LLM runtime? Neither has a mechanical consumer — their only
# possible value is the context they carry into later stages and the final report.
#
# Three arms over the same names, same day, same cached research brief (so all arms read
# identical evidence). Output isolated to ab_reports/ablation/<arm>/ — the overlay only reads
# CONFIG["out_reports_dir"], so no experimental verdict can reach the live site.
set -u
cd "$(dirname "$0")/../.." || exit 1
NAMES=$(python -c "import json;print(' '.join(json.load(open('cache/_ablation_sample.json'))))")
echo "sample: $NAMES"
for ARM in full no_s2 no_s6; do
  case "$ARM" in
    full)  DROP="" ;;
    no_s2) DROP="--drop-stage S2_quality" ;;
    no_s6) DROP="--drop-stage S6_redteam_audit" ;;
  esac
  for T in $NAMES; do
    echo "=== [$ARM] $T $(date +%H:%M:%S) ==="
    python run_rs2.py "$T" --ablation "$ARM" $DROP >> "ab_reports/ablation/_${ARM}.log" 2>&1
    echo "    exit=$? $(date +%H:%M:%S)"
  done
done
echo "ABLATION COMPLETE $(date +%H:%M:%S)"
