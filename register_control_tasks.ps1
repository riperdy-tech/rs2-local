# register_control_tasks.ps1
# Registers the control-tower scheduled tasks. Mirrors register_depth_task.ps1
# conventions: interactive-logon principal, cmd /c with log redirect, WD = repo.
# Timezone note: this PC is UTC+08:00 (no DST). 22:35 local = 14:35 UTC (weekday
# SDF primary target); 18:35 local = 10:35 UTC (weekend target).

$ErrorActionPreference = "Stop"

$repo = "C:\Users\riper\Downloads\RS2 Local"
$py   = "C:\Program Files\Python312\python.exe"
$gh   = "C:\Program Files\GitHub CLI\gh.exe"

# Pin the principal explicitly (like the sibling scripts): gh.exe auth is
# user-scoped, so the SDF dispatch must run as this interactive user.
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" `
  -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# --- RS2-Control-Agent: every 5 minutes, forever -----------------------------
# Argument quoting follows register_bot_task.ps1 / register_depth_task.ps1:
# cmd /c needs the WHOLE payload wrapped in an outer quote pair or the >> redirect
# is parsed away and the task exits 1 with no log.
$agentArg = "/c `"`"$py`" `"$repo\control_agent.py`" >> `"$repo\cache\control_agent_task.log`" 2>&1`""
$agentAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $agentArg -WorkingDirectory $repo
# NOTE: -RepetitionDuration ([TimeSpan]::MaxValue) and [TimeSpan]::Zero are both
# rejected on this Windows build (HRESULT 0x80041318), and -RepetitionInterval
# requires SOME duration at build time. An ABSENT <Duration> means "repeat
# indefinitely", so build with a placeholder day and null it afterwards.
$agentTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 5) `
  -RepetitionDuration (New-TimeSpan -Days 1)
$agentTrigger.Repetition.Duration = $null
$agentTrigger.Repetition.StopAtDurationEnd = $false
Register-ScheduledTask -TaskName "RS2-Control-Agent" -Action $agentAction `
  -Trigger $agentTrigger -Settings $settings -Principal $principal `
  -Description "RS2 control tower agent: 5-min heartbeat to Supabase + remote command executor." -Force

# --- RS2-SDF-Dispatch: the SDF PC self-dispatch primary ----------------------
$sdfArg = "/c `"`"$gh`" workflow run schedule-data-fetch.yml -R riperdy-tech/stock-screener -f runner=self-hosted >> `"$repo\cache\sdf_dispatch.log`" 2>&1`""
$sdfAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $sdfArg -WorkingDirectory $repo
$sdfTriggers = @(
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "22:35"),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday,Sunday -At "18:35")
)
Register-ScheduledTask -TaskName "RS2-SDF-Dispatch" -Action $sdfAction `
  -Trigger $sdfTriggers -Settings $settings -Principal $principal `
  -Description "SDF PC self-dispatch primary: gh workflow run schedule-data-fetch.yml -f runner=self-hosted (22:35 wd / 18:35 we local)." -Force

Write-Host "Registered RS2-Control-Agent (q5min) and RS2-SDF-Dispatch (22:35 wd / 18:35 we local)."
