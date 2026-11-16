# Registers RS2-Monitor-Daily: the holdings monitor's daily gather and run pass (monitor_daily.ps1), 05:55 local, outside any
# Claude session, no window. One instance (IgnoreNew, and the monitor's own locks). Paper only.
#   .\register_monitor_task.ps1
# Remove with: .\register_monitor_task.ps1 -Remove
param([switch]$Remove)
$name = "RS2-Monitor-Daily"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$here\monitor_daily.ps1`"" -WorkingDirectory $here
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 8) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At "05:55") -Settings $settings `
    -Principal $principal -Description "Holdings monitor: daily gather (after the B2 gather, in the Docker window) and one run pass on the GPU. tools/holdings_monitor/monitor_daily.ps1" -Force | Out-Null
"registered $name"
