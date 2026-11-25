# Registers RS2-News-Watch: the daily news check of the analysed stocks (tools/site/news_watch.py morning) outside any Claude session,
# through news_watch_hidden.vbs. Daily 06:00 local (21:00 UTC, after the US close), inside the Docker window that
# tools/b2_recall/docker_window.ps1 opens at 05:40 for SearXNG; the gather's marker (cache\monitor_gather.running in the main working
# tree) keeps that window open until the gather is over. Never doubled (IgnoreNew + news_watch's lock).
#   .\register_news_watch_task.ps1
# Remove with: .\register_news_watch_task.ps1 -Remove
param([switch]$Remove)
$name = "RS2-News-Watch"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\news_watch_hidden.vbs`"" -WorkingDirectory $root
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At "06:00") -Settings $settings -Principal $principal `
    -Description "News on the analysed stocks for stockpeak.net: gather, check against each stock's own points, warnings. tools/site/news_watch.py" -Force | Out-Null
"registered $name"
