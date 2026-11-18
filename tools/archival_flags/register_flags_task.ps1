# Registers RS2-Flags-Run: the B3b flags pass (flags_run.py run through flags_run_hidden.vbs), started by hand (schtasks /run) and
# again at logon, so a reboot (Windows Update killed the cohort run unnoticed on 2026-11-12) resumes it. The pass is resumable and
# single-instance; when every slot is final it reads nothing and exits. Remove with: .\register_flags_task.ps1 -Remove
param([switch]$Remove)
$name = "RS2-Flags-Run"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Days 5) -StartWhenAvailable
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\flags_run_hidden.vbs`"" -WorkingDirectory $root
Register-ScheduledTask -TaskName $name -Action $action -Trigger (New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME") `
    -Settings $settings -Principal $principal -Force `
    -Description "PREREG B3b: the material_events read of the four archival cohorts' packets into cache/m3m_flags. Log cache/flags_run_task.log. tools/archival_flags/flags_run.py" | Out-Null
"registered"
