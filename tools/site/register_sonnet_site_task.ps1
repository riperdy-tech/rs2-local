# Registers RS2-Sonnet-Site: the Claude Sonnet arm of the list worker (tools/site/gemini_ondemand.py --arm sonnet work) outside any Claude session, through
# sonnet_site_hidden.vbs. Starts at logon and every 15 minutes; never doubled (IgnoreNew + the worker's lock). No GPU: the worker
# paces itself on the Claude subscription's own five-hour and weekly meters and waits for the reset when either is low.
#   .\register_sonnet_site_task.ps1
# Remove with: .\register_sonnet_site_task.ps1 -Remove
param([switch]$Remove)
$name = "RS2-Sonnet-Site"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\sonnet_site_hidden.vbs`"" -WorkingDirectory $root
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $every) -Settings $settings -Principal $principal `
    -Description "Claude Sonnet arm of the list analysis for stockpeak.net (first fill). tools/site/gemini_ondemand.py --arm sonnet" -Force | Out-Null
"registered $name"
