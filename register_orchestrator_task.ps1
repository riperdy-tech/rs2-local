# register_orchestrator_task.ps1 — register the "RS2-Orchestrator" Windows Scheduled Task.
# Runs orchestrate.py daily (06:00) + at logon, unattended (no Claude agent involved).
# Prereqs at run time: Ollama app up (it starts at logon) and Docker/SearXNG if Tavily is capped.
# The orchestrator health-checks Ollama and exits cleanly if it's down.
#
# Run this script ONCE (normal user PowerShell — a per-user task needs no admin):
#     powershell -ExecutionPolicy Bypass -File register_orchestrator_task.ps1
# Remove later:  Unregister-ScheduledTask -TaskName "RS2-Orchestrator" -Confirm:$false

$ErrorActionPreference = "Stop"
$root = "C:\Users\riper\Downloads\RS2 Local"
$py   = "C:\Program Files\Python312\python.exe"
$log  = "$root\reports\_orchestrate.log"
$name = "RS2-Orchestrator"

# Wrap in cmd so stdout/stderr append to a log (Task Scheduler doesn't capture them itself).
$cmd = "/c `"`"$py`" `"$root\orchestrate.py`" >> `"$log`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument $cmd -WorkingDirectory $root

# 08:00 TPE (00:00 UTC): after the 21:05 UTC Post-Close Price Refresh (+ its
# 0-3h GitHub jitter) has re-scored bands on today's actual US closes, so RS2
# reviews same-day closing data instead of yesterday's.
$t1 = New-ScheduledTaskTrigger -Daily -At 8:00am
$t2 = New-ScheduledTaskTrigger -AtLogOn
# StartWhenAvailable = catch up if the PC was off at 6am; WakeToRun; no execution time limit (backfill is long).
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -WakeToRun -DontStopOnIdleEnd `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $t1, $t2 `
    -Settings $settings -Principal $principal `
    -Description "Local RS2 LLM: analyze Research-Now + Watchlist names, push llm_overlay.json to the screener." `
    -Force | Out-Null

Write-Output "Registered scheduled task '$name' (daily 08:00 + at logon)."
Write-Output "  log: $log"
Write-Output "  run now:   Start-ScheduledTask -TaskName '$name'"
Write-Output "  status:    Get-ScheduledTaskInfo -TaskName '$name'"
Write-Output "  remove:    Unregister-ScheduledTask -TaskName '$name' -Confirm:`$false"
Write-Output ""
Write-Output "NOTE: backfill is already complete (171/171). Scheduled runs now only refresh DUE names"
Write-Output "      (Research-Now > 7d, Watchlist > 14d) + any new entrants, then push llm_overlay.json + rs2/ reports."
Write-Output "      Queue stays near-empty until names age past the refresh window. Preview anytime: python orchestrate.py --dry-run"
