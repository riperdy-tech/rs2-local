# register_control_tasks.ps1
# Registers the control-tower scheduled tasks. Mirrors register_depth_task.ps1
# conventions: interactive-logon principal, cmd /c with log redirect, WD = repo.
# Timezone note: this PC is UTC+08:00 (no DST). 22:35 local = 14:35 UTC (weekday
# SDF primary target); 18:35 local = 10:35 UTC (weekend target).

$repo = "C:\Users\riper\Downloads\RS2 Local"
$py   = "C:\Program Files\Python312\python.exe"
$gh   = "C:\Program Files\GitHub CLI\gh.exe"

$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable `
  -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30)

# --- RS2-Control-Agent: every 5 minutes, forever -----------------------------
# Argument quoting follows register_bot_task.ps1 / register_depth_task.ps1:
# cmd /c needs the WHOLE payload wrapped in an outer quote pair or the >> redirect
# is parsed away and the task exits 1 with no log.
$agentArg = "/c `"`"$py`" `"$repo\control_agent.py`" >> `"$repo\cache\control_agent_task.log`" 2>&1`""
$agentAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $agentArg -WorkingDirectory $repo
# Indefinite repetition: this Windows build rejects BOTH [TimeSpan]::MaxValue
# (Duration P99999999DT23H59M59S) and [TimeSpan]::Zero (PT0S) with
# "task XML contains a value which is incorrectly formatted or out of range"
# (HRESULT 0x80041318). The XML the service accepts for "forever" is an ABSENT
# <Duration> element, which is what nulling the property produces.
$agentTrigger = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) `
  -RepetitionInterval (New-TimeSpan -Minutes 5) `
  -RepetitionDuration (New-TimeSpan -Days 1)
$agentTrigger.Repetition.Duration = $null
$agentTrigger.Repetition.StopAtDurationEnd = $false
Register-ScheduledTask -TaskName "RS2-Control-Agent" -Action $agentAction `
  -Trigger $agentTrigger -Settings $settings -Force

# --- RS2-SDF-Dispatch: the SDF PC self-dispatch primary ----------------------
$sdfArg = "/c `"`"$gh`" workflow run schedule-data-fetch.yml -R riperdy-tech/stock-screener -f runner=self-hosted >> `"$repo\cache\sdf_dispatch.log`" 2>&1`""
$sdfAction = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $sdfArg -WorkingDirectory $repo
$sdfTriggers = @(
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Monday,Tuesday,Wednesday,Thursday,Friday -At "22:35"),
  (New-ScheduledTaskTrigger -Weekly -DaysOfWeek Saturday,Sunday -At "18:35")
)
Register-ScheduledTask -TaskName "RS2-SDF-Dispatch" -Action $sdfAction `
  -Trigger $sdfTriggers -Settings $settings -Force

Write-Host "Registered RS2-Control-Agent (q5min) and RS2-SDF-Dispatch (22:35 wd / 18:35 we local)."
