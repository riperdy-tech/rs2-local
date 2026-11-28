# Registers RS2-Daily-Report: one Telegram message a day (tools/site/daily_report.py send) outside any Claude session, through
# daily_report_hidden.vbs. Daily 14:00 local, after the site's post-close run (about 12:30 to 13:00 here on the day after a US session).
# Register it from the working tree the site worker runs from, so that it reads that tree's logs.
#   .\register_daily_report_task.ps1
# Remove with: .\register_daily_report_task.ps1 -Remove
param([switch]$Remove)
$name = "RS2-Daily-Report"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\daily_report_hidden.vbs`"" -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At "14:00") -Settings $settings -Principal $principal `
    -Description "Daily Telegram report: did every job run, the AI book, what it bought and sold. tools/site/daily_report.py" -Force | Out-Null
"registered $name"
