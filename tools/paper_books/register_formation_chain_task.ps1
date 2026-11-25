# Registers RS2-Formation-Chain for one formation date: formation_chain.py every 30 minutes, outside any Claude session, through
# formation_chain_hidden.vbs. RUN THIS FILE FROM THE TREE THE SITE WORKER RUNS FROM (the chain's read takes that tree's worker lock).
# The first pass is at -Start (default: 06:20 local time on the day after the formation date, just after the New York close in Korea).
# Never doubled (IgnoreNew); idle once cache\paper_books\formation\chain_published_<date>.flag exists.
#   .\register_formation_chain_task.ps1 -Formation 2026-11-30
# Remove with: .\register_formation_chain_task.ps1 -Remove
param([string]$Formation, [datetime]$Start, [switch]$Remove)
$name = "RS2-Formation-Chain"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed $name"; return }
if ($Formation -notmatch '^\d{4}-\d{2}-\d{2}$') { throw "give the formation date: -Formation YYYY-MM-DD" }
if (-not $Start) { $Start = ([datetime]::ParseExact($Formation, 'yyyy-MM-dd', $null)).AddDays(1).AddHours(6).AddMinutes(20) }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\formation_chain_hidden.vbs`" $Formation" -WorkingDirectory $root
$every = New-ScheduledTaskTrigger -Once -At $Start -RepetitionInterval (New-TimeSpan -Minutes 30)
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit ([TimeSpan]::Zero) `
    -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
Register-ScheduledTask -TaskName $name -Action $action -Trigger $every -Settings $settings -Principal $principal `
    -Description "Month-end formation $Formation on the cloud reader: decide, packets, read, freeze before the fill open, books file. tools/paper_books/formation_chain.py. Remove when chain_published_$Formation.flag exists." -Force | Out-Null
"registered $name for $Formation, first pass $Start"
