# register_grader_task.ps1 — register the "RS2-Depth-Grader" Windows Scheduled Task.
#
# Runs tools/grade_depth_verdicts.py (TRK-06, P2.5) unattended, once a week, with a network price
# fetch. Mirrors register_depth_task.ps1's structure; this task is far lighter (one price fetch +
# grading pass, not a multi-hour LLM sweep) so a single weekly anchor is enough — the sweep itself
# also re-runs the grader --offline at the end of every cycle (orchestrate_depth.main()), so the
# ledger's own cadence keeps cache/depth_outcomes.json current between weekly network refreshes.
#
# CADENCE: Sunday 09:00 (Design, PHASE_2_DEPTH_SCOREBOARD.md P2.5) — off the depth sweep's own
# 4-hourly cadence so a stalled/slow sweep never delays the grader, and a quiet weekend morning
# for the network fetch.
#
# OPERATOR-APPROVAL REQUIRED: this script is prepared, not registered. Registering a Windows
# Scheduled Task is a machine change (Phase 2 operator ruling, 2026-09-23) — run it yourself when
# ready; nothing in this change invokes it.
#
# Run ONCE (normal user PowerShell — a per-user task needs no admin):
#     powershell -ExecutionPolicy Bypass -File register_grader_task.ps1
# Remove later:  Unregister-ScheduledTask -TaskName "RS2-Depth-Grader" -Confirm:$false

$ErrorActionPreference = "Stop"
# The repo root, derived so a folder move needs no edit here: re-running this
# script from its new location re-registers the task against the new path.
$root = $PSScriptRoot
$py   = "C:\Program Files\Python312\python.exe"
$log  = "$root\cache\depth_grader_task.log"
$name = "RS2-Depth-Grader"

# Wrap in cmd so stdout/stderr append to a log (Task Scheduler doesn't capture them itself).
$cmd = "/c `"`"$py`" `"$root\tools\grade_depth_verdicts.py`" >> `"$log`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument $cmd -WorkingDirectory $root

$t = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 9:00am

# StartWhenAvailable = catch up if the PC was off at 09:00 Sunday; 1-hour execution time limit
# (C10, Phase 2 approval review: a price fetch + grading pass is minutes, not hours — unlike the
# orchestrator's multi-hour LLM sweep, an unbounded limit here would only hide a real hang); no
# WakeToRun — a grading pass is not worth waking the PC for, unlike the depth sweep itself;
# IgnoreNew = never double-start.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit ([TimeSpan]::FromHours(1)) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $t `
    -Settings $settings -Principal $principal `
    -Description "RS2 depth tier: TRK-06 forward-return grading -> cache/depth_outcomes.json + reports/depth_outcomes_report.md." `
    -Force | Out-Null

Write-Output "Registered scheduled task '$name' (weekly, Sunday 09:00)."
Write-Output "  log:     $log"
Write-Output "  run now: Start-ScheduledTask -TaskName '$name'"
Write-Output "  status:  Get-ScheduledTaskInfo -TaskName '$name'"
Write-Output "  remove:  Unregister-ScheduledTask -TaskName '$name' -Confirm:`$false"
