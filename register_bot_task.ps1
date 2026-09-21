# register_bot_task.ps1 — register the "RS2-Telegram-Bot" Windows Scheduled Task.
#
# Keeps telegram_status_bot.py alive unattended. The bot is no longer a convenience:
# it is the INBOUND BRIDGE for the site's /ondemand "Analyze" button (it drains the
# Supabase ondemand_queue table), so a hand-started foreground bot means a website
# button that silently does nothing after the next reboot. AtLogOn trigger + restart
# on failure make it a service in practice; MultipleInstances IgnoreNew prevents a
# second copy fighting the first over the getUpdates offset.
#
# Run ONCE (normal user PowerShell — a per-user task needs no admin):
#     powershell -ExecutionPolicy Bypass -File register_bot_task.ps1
# Remove later:  Unregister-ScheduledTask -TaskName "RS2-Telegram-Bot" -Confirm:$false

$ErrorActionPreference = "Stop"
# The repo root, derived so a folder move needs no edit here: re-running this
# script from its new location re-registers the task against the new path.
$root = $PSScriptRoot
$py   = "C:\Program Files\Python312\python.exe"
$log  = "$root\cache\telegram_bot_task.log"
$name = "RS2-Telegram-Bot"

# Wrap in cmd so stdout/stderr append to a log (Task Scheduler doesn't capture them itself).
$cmd = "/c `"`"$py`" `"$root\telegram_status_bot.py`" >> `"$log`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "$env:SystemRoot\System32\cmd.exe" -Argument $cmd -WorkingDirectory $root

$t = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"

# No execution time limit (the bot long-polls forever); restart if it crashes.
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -DontStopOnIdleEnd `
    -ExecutionTimeLimit ([TimeSpan]::Zero) -MultipleInstances IgnoreNew `
    -RestartInterval (New-TimeSpan -Minutes 5) -RestartCount 999
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

Register-ScheduledTask -TaskName $name -Action $action -Trigger $t `
    -Settings $settings -Principal $principal `
    -Description "RS2 Telegram bot: /status + /analyze commands, and the web ondemand_queue bridge for the site's Analyze button." `
    -Force | Out-Null

Write-Output "Registered scheduled task '$name' (at logon, auto-restart on crash)."
Write-Output "  log:     $log"
Write-Output "  run now: Start-ScheduledTask -TaskName '$name'"
Write-Output "  status:  Get-ScheduledTaskInfo -TaskName '$name'"
Write-Output "  remove:  Unregister-ScheduledTask -TaskName '$name' -Confirm:`$false"
