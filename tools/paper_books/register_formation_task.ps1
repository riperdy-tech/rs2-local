# Registers RS2-Formation-Runner for one formation date: runs that formation's qwen_c runs (formation_run.py) outside any Claude session
# (memory: long runs outside Claude), through formation_run_hidden.vbs. Starts at logon and every 15 minutes; never doubled
# (IgnoreNew + formation_run.py's runner.lock); idle once cache\paper_books\formation\finished_<date>.flag exists.
# Run it only after formation_decide.py and formation_packets.py have written and filled the map (README, "Monthly formation").
#   .\register_formation_task.ps1 -Formation 2026-11-30
# Remove with: .\register_formation_task.ps1 -Remove
param([string]$Formation, [switch]$Remove)
$name = "RS2-Formation-Runner"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
if ($Formation -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "give the formation date: -Formation YYYY-MM-DD" }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\formation_run_hidden.vbs`" $Formation" -WorkingDirectory $root
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $every) -Settings $settings -Principal $principal `
    -Description "AI-book formation (WO_O2): qwen_c full runs over the $Formation A0 book. Remove when cache\paper_books\formation\finished_$Formation.flag exists. tools/paper_books/formation_run.py" -Force | Out-Null
"registered $name for $Formation"
