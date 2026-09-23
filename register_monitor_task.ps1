# register_monitor_task.ps1 — register the "RS2-Thesis-Monitor" Windows Scheduled Task.
#
# P4.5/DEP-13: runs `orchestrate_depth.py --monitor` unattended — thesis_monitor.run() +
# rebuild_overlay() + publish_overlay(), NO GPU, NO analyst. Mirrors register_depth_task.ps1's
# shape; the cadence differs (once daily, not every 4h — the underlying data it checks against
# (fundamentals_quarterly.json, fundamentals_ttm.json, fundamentals_battery.json,
# factor_scores.json) moves at most daily, so a tighter cadence would buy nothing).
#
# PREPARED, NOT REGISTERED (operator approval — PHASE_4_ANALYST.md P4.5): running this script is
# the approval step. It is committed so the operator can review it and register it later with one
# command; nothing in this change runs it.
#
# Gated by cache/DEPTH_PAUSED exactly like RS2-Depth-Orchestrator, with one exception the script
# itself enforces: `--monitor --no-publish` still runs while paused (restricted to writing
# cache/depth_thesis.json only) — see orchestrate_depth.run_monitor(). This task does NOT pass
# --no-publish, so it is fully paused like the sweep; run it manually with --no-publish if a
# no-footprint read is wanted during a halt.
#
# Run ONCE (normal user PowerShell — a per-user task needs no admin):
#     powershell -ExecutionPolicy Bypass -File register_monitor_task.ps1
# Remove later:  Unregister-ScheduledTask -TaskName "RS2-Thesis-Monitor" -Confirm:$false

$ErrorActionPreference = "Stop"
# The repo root, derived so a folder move needs no edit here.
$root = $PSScriptRoot
$py   = "C:\Program Files\Python312\python.exe"
$log  = "$root\cache\depth_monitor_task.log"
$name = "RS2-Thesis-Monitor"

# Wrap in cmd so stdout/stderr append to a log (Task Scheduler doesn't capture them itself).
$cmd = "/c `"`"$py`" `"$root\orchestrate_depth.py`" --monitor >> `"$log`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument $cmd -WorkingDirectory $root

# Once daily, 06:00 — ahead of the 02:00 depth sweep's own membership/trigger read by a few
# hours so a stale thesis read is never the reason a 02:00 sweep queues (or fails to queue) a name.
$t = New-ScheduledTaskTrigger -Daily -At 6:00am

# StartWhenAvailable = catch up if the PC was off at 06:00; WakeToRun; the run is short (no GPU,
# no analyst) so no extended execution-time limit is needed. IgnoreNew = never double-start.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopOnIdleEnd `
    -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $t `
    -Settings $settings -Principal $principal `
    -Description "RS2 thesis monitor: DEP-13 rule re-checks -> cache/depth_thesis.json, merged into depth_overlay.json." `
    -Force | Out-Null

Write-Output "Registered scheduled task '$name' (daily 06:00)."
Write-Output "  log:     $log"
Write-Output "  run now: Start-ScheduledTask -TaskName '$name'"
Write-Output "  status:  Get-ScheduledTaskInfo -TaskName '$name'"
Write-Output "  pause:   New-Item '$root\cache\DEPTH_PAUSED' -ItemType File   (also pauses this task)"
Write-Output "  remove:  Unregister-ScheduledTask -TaskName '$name' -Confirm:`$false"
