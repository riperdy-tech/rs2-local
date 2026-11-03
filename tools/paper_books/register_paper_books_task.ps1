# Registers the monthly paper-books run (moved into git from an untracked scratch folder 2026-11-03):
#   RS2-Paper-Books   monthly on days 1, 2 and 3 at 08:00 local (KST: the US month-end close has passed), run_monthly.py
#                     through run_paper_books_hidden.vbs (no console window; the task result is the run's exit code)
# Code: tools/paper_books/ (this folder). Books: <rs2_state_dir>/paper_books (paths.py). Log: cache/paper_books.log.
# A day whose last completed New York session is already marked does nothing, so the three days are retries and late fills.
# Remove with: .\register_paper_books_task.ps1 -Remove
param([switch]$Remove)
$name = "RS2-Paper-Books"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\run_paper_books_hidden.vbs`"" -WorkingDirectory $root
# New-ScheduledTaskTrigger has no monthly form: register with a placeholder trigger, then set the monthly one through the COM API.
Register-ScheduledTask -TaskName $name -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At "08:00") -Settings $settings `
    -Principal $principal -Force `
    -Description "Paper books, monthly: archive and verify new screener GitHub runs, forward_ledger (A0), universe prices, m3o_engine; commit and push rs2-state paper_books/. Exit 1 on any failed step (cache/paper_books.log). tools/paper_books/run_monthly.py" | Out-Null
$svc = New-Object -ComObject "Schedule.Service"; $svc.Connect()
$folder = $svc.GetFolder("\")
$def = $folder.GetTask($name).Definition
$def.Triggers.Clear()
$t = $def.Triggers.Create(4)                                  # TASK_TRIGGER_MONTHLY
$t.DaysOfMonth = 7                                            # bit mask: day 1 (1) + day 2 (2) + day 3 (4)
$t.MonthsOfYear = 4095                                        # all twelve months
$t.StartBoundary = (Get-Date -Hour 8 -Minute 0 -Second 0).ToString("yyyy-MM-dd'T'HH:mm:ss")
$folder.RegisterTaskDefinition($name, $def, 4, $null, $null, 3) | Out-Null   # TASK_UPDATE; TASK_LOGON_INTERACTIVE_TOKEN
"registered"
