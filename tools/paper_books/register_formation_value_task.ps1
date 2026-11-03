# Registers RS2-Formation-Value for one formation date: the F10 menu valuations of that formation's A0 book (formation_value.py) outside
# any Claude session (memory: long runs outside Claude), through formation_value_hidden.vbs. Starts at logon and every 15 minutes; never
# doubled (IgnoreNew + formation_value.py's value.lock). Register it together with RS2-Formation-Runner: its first passes pin the anchors
# as of T and then wait, so no valuation starts before cache\paper_books\formation\finished_<date>.flag; it is idle once
# value_finished_<date>.flag exists, and stops on value_STOP_<date>.flag until a human looks (README, "Monthly formation").
#   .\register_formation_value_task.ps1 -Formation 2026-11-30
# Remove with: .\register_formation_value_task.ps1 -Remove
param([string]$Formation, [switch]$Remove)
$name = "RS2-Formation-Value"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
if ($Formation -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "give the formation date: -Formation YYYY-MM-DD" }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\formation_value_hidden.vbs`" $Formation" -WorkingDirectory $root
$logon = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$every = New-ScheduledTaskTrigger -Once -At (Get-Date).AddMinutes(1) -RepetitionInterval (New-TimeSpan -Minutes 15)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger @($logon, $every) -Settings $settings -Principal $principal `
    -Description "F10 menu valuations of the $Formation A0 book (seeds 1000, 3000), after its Q1 runs finish. Remove when cache\paper_books\formation\value_finished_$Formation.flag exists. tools/paper_books/formation_value.py" -Force | Out-Null
"registered $name for $Formation"
