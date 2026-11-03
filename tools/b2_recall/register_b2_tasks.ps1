# Registers the P6.7 B2 recall gather and the Docker window it needs (moved here from a Claude temp scratchpad 2026-11-03):
#   RS2-B2-Gather-P6         daily 06:00 local, b2_day.py (its data: paths.py b2_recall_dir)
#   RS2-Docker-Window-Start  daily 05:40 local, starts Docker Desktop and SearXNG
#   RS2-Docker-Window-Stop   daily 06:20 local, stops Docker once no gather is running
# Remove with: .\register_b2_tasks.ps1 -Remove
param([switch]$Remove)
$names = "RS2-B2-Gather-P6", "RS2-Docker-Window-Start", "RS2-Docker-Window-Stop"
if ($Remove) { foreach ($n in $names) { Unregister-ScheduledTask -TaskName $n -Confirm:$false }; "removed"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited

$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 4) -StartWhenAvailable
$action = New-ScheduledTaskAction -Execute "C:\Program Files\Python312\python.exe" -Argument "-u `"$here\b2_day.py`"" -WorkingDirectory $here
Register-ScheduledTask -TaskName "RS2-B2-Gather-P6" -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At "06:00") -Settings $settings -Principal $principal `
    -Description "P6.7 acceptance B2: one daily follow-up gather over the 104 recall names (frozen tree rs2-B2, no GPU). Exits 2 when SearXNG is down or news queries errored. tools/b2_recall/b2_day.py" -Force | Out-Null

$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 3) -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
foreach ($p in @(@("RS2-Docker-Window-Start", "-Start", "05:40"), @("RS2-Docker-Window-Stop", "-Stop", "06:20"))) {
    $action = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$here\docker_window.ps1`" $($p[1])" -WorkingDirectory $here
    Register-ScheduledTask -TaskName $p[0] -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At $p[2]) -Settings $settings -Principal $principal `
        -Description "Docker Desktop on only for the 06:00 RS2-B2-Gather-P6 news gather (SearXNG). tools/b2_recall/docker_window.ps1" -Force | Out-Null
}
"registered"
