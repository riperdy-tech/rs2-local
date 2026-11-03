# Registers RS2-Reference-Closure: tools/closure_monthly.py on the 15th of each month at 06:30, hidden, logging to
# cache\closure_monthly.log. Network only (Yahoo); no GPU. Remove with: .\register_closure_task.ps1 -Remove
param([switch]$Remove)
$name = "RS2-Reference-Closure"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent $here
$py = "C:\Program Files\Python312\python.exe"
$cmd = "/c `"`"$py`" -u `"$here\closure_monthly.py`" >> `"$root\cache\closure_monthly.log`" 2>&1`""
$action = New-ScheduledTaskAction -Execute "cmd.exe" -Argument $cmd -WorkingDirectory $root
$monthly = New-ScheduledTaskTrigger -Daily -At "06:30"     # placeholder; replaced by the monthly trigger below
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 6) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable -Hidden
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $monthly -Settings $settings -Principal $principal `
    -Description "Monthly rebuild of rs2-local cache/reference_closure.json (tools/closure_monthly.py), the 15th at 06:30" -Force | Out-Null
# PowerShell has no monthly trigger cmdlet: set the day-of-month trigger through the COM schema
$svc = New-Object -ComObject Schedule.Service; $svc.Connect()
$task = $svc.GetFolder("\").GetTask($name)
$def = $task.Definition
$def.Triggers.Clear()
$tr = $def.Triggers.Create(4)            # TASK_TRIGGER_MONTHLY
$tr.StartBoundary = (Get-Date -Hour 6 -Minute 30 -Second 0).ToString("yyyy-MM-ddTHH:mm:ss")
$tr.DaysOfMonth = 1 -shl 14              # bit 14 = the 15th
$tr.MonthsOfYear = 0xFFF
$svc.GetFolder("\").RegisterTaskDefinition($name, $def, 6, $null, $null, 3) | Out-Null
"registered $name (monthly, the 15th, 06:30)"
