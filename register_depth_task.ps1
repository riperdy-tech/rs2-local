# register_depth_task.ps1 — register the "RS2-Depth-Orchestrator" Windows Scheduled Task.
#
# Runs orchestrate_depth.py (the DEPTH tier, band-direction verdicts) unattended. Successor to the
# retired RS2-Orchestrator task, which drove the dropped production pipeline and stays disabled via
# cache/PAUSED. This one is gated by cache/DEPTH_PAUSED instead.
#
# CADENCE (DEPTH_ORCHESTRATOR_CADENCE_20260825.md): the sweep processes the whole trigger queue in
# one invocation, one child at a time, then exits. Anchored at 02:00 and repeated every 4h so new
# intraday triggers (price moves, fresh filings) get picked up the same day. MultipleInstances=
# IgnoreNew means a repeat that lands while a long sweep is still running is skipped, not doubled.
#
# Prereqs at run time: Ollama up (starts at logon); SearXNG/Docker if Tavily is capped. The
# orchestrator health-checks and exits cleanly if the model host is down.
#
# Run ONCE (normal user PowerShell — a per-user task needs no admin):
#     powershell -ExecutionPolicy Bypass -File register_depth_task.ps1
# Remove later:  Unregister-ScheduledTask -TaskName "RS2-Depth-Orchestrator" -Confirm:$false

$ErrorActionPreference = "Stop"
$root = "C:\Users\riper\Downloads\RS2 Local"
$py   = "C:\Program Files\Python312\python.exe"
$log  = "$root\cache\depth_orchestrate_task.log"
$name = "RS2-Depth-Orchestrator"

# Wrap in cmd so stdout/stderr append to a log (Task Scheduler doesn't capture them itself).
$cmd = "/c `"`"$py`" `"$root\orchestrate_depth.py`" >> `"$log`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument $cmd -WorkingDirectory $root

# 02:00 anchor, then repeat every 4h for 24h so the queue stays responsive through the day.
$t = New-ScheduledTaskTrigger -Daily -At 2:00am
$t.Repetition = (New-ScheduledTaskTrigger -Once -At 2:00am `
    -RepetitionInterval (New-TimeSpan -Hours 4) `
    -RepetitionDuration (New-TimeSpan -Hours 24)).Repetition

# StartWhenAvailable = catch up if the PC was off at 02:00; WakeToRun; no execution time limit
# (a full sweep can run many hours). IgnoreNew = never double-start a sweep already running.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopOnIdleEnd `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $t `
    -Settings $settings -Principal $principal `
    -Description "RS2 depth tier: trigger-driven band-direction verdicts -> cache/depth_ledger.jsonl + depth_overlay.json." `
    -Force | Out-Null

Write-Output "Registered scheduled task '$name' (daily 02:00, repeat every 4h)."
Write-Output "  log:     $log"
Write-Output "  run now: Start-ScheduledTask -TaskName '$name'"
Write-Output "  status:  Get-ScheduledTaskInfo -TaskName '$name'"
Write-Output "  pause:   New-Item '$root\cache\DEPTH_PAUSED' -ItemType File   (stops at next ticker boundary)"
Write-Output "  remove:  Unregister-ScheduledTask -TaskName '$name' -Confirm:`$false"
