# Registers RS2-Qwen-Site: the Qwen site worker (tools/site/qwen_ondemand.py work) outside any Claude session, through
# qwen_site_hidden.vbs. Starts at logon and every 15 minutes; never doubled (IgnoreNew + the worker's lock). The worker takes the GPU
# only between names and only when cache\site\GPU_HOLD is absent and no other job holds the card (agreed with F03, 2026-11-06).
#   .\register_qwen_site_task.ps1
# Remove with: .\register_qwen_site_task.ps1 -Remove
param([switch]$Remove)
$name = "RS2-Qwen-Site"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\qwen_site_hidden.vbs`"" -WorkingDirectory $root
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $every) -Settings $settings -Principal $principal `
    -Description "Qwen analysis for stockpeak.net: on-demand requests, then the screener list refreshed every 14 days. tools/site/qwen_ondemand.py" -Force | Out-Null
"registered $name"
