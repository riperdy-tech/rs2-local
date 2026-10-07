# Registers RS2-Gate2-Replay: keeps the gate-2 Muse replay alive OUTSIDE any Claude session (2026-10-06: a Claude desktop update closed every process started under the app).
# Starts at logon and every 15 minutes; a running copy is never doubled (IgnoreNew here, and the runner's own runner.lock).
#
#   .\register_gate2_task.ps1 -Mode pilot     the pilot (10 company-dates of 2025-10-31; the report is timing only; the outputs are sealed)
#   .\register_gate2_task.ps1 -Mode full      the replay (the pilot's companies are already done and are skipped)
#   .\register_gate2_task.ps1 -Mode masked    the G6 control of 30 company-dates with name and ticker masked (after the replay)
#   .\register_gate2_task.ps1 -Remove         remove the task (do this when gate2_finished.flag exists)
#
# NOT registered by whoever built it: the coordinator runs this after the sample is drawn, the freeze is written (freeze_content write) and the readiness checks pass.
# The state (progress.jsonl, events.jsonl, the run folders, runner.out/err, the PAUSE switch) is under -StateDir, default <STOCKS_ROOT>\stocks-workspace\data\gate2.
# Pause: create <StateDir>\PAUSE (delete it to resume).  The runner stops its server while paused and while another program uses the GPU.
param([ValidateSet("pilot", "full", "masked")][string]$Mode = "pilot", [string]$StateDir = "", [switch]$Remove, [string]$Name = "RS2-Gate2-Replay")
if ($Remove) { Unregister-ScheduledTask -TaskName $Name -Confirm:$false; "removed $Name"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
if ($StateDir -eq "") {
    if ($env:GATE2_STATE_DIR) { $StateDir = $env:GATE2_STATE_DIR }
    else {
        $root = if ($env:STOCKS_ROOT) { $env:STOCKS_ROOT } else { "C:\Users\riper\stocks" }
        $StateDir = Join-Path $root "stocks-workspace\data\gate2"
    }
}
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\launch_gate2.vbs`" $Mode `"$StateDir`"" -WorkingDirectory $here
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable `
    -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 5)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $Name -Action $action -Trigger @($logon, $every) -Settings $settings -Principal $principal `
    -Description "Gate 2 Muse replay ($Mode), state in $StateDir. Remove when gate2_finished.flag exists." -Force | Out-Null
"registered $Name ($Mode), state $StateDir"
