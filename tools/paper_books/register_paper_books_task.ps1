# Registers the paper-books run (moved into git from an untracked scratch folder 2026-11-03; daily since 2026-11-18):
#   RS2-Paper-Books   daily at 09:00 local (KST: the US close has passed and the holdings monitor's morning run has ended),
#                     run_monthly.py through run_paper_books_hidden.vbs (no console window; the task result is the run's exit code).
#                     Daily, not days 1 to 3: book FV's exits (tools/holdings_monitor/fv_actions.py) reach the ledger only when the
#                     engine runs on fresh prices. The run is idempotent per New York session, so a day with no new session does nothing.
# Code: tools/paper_books/ (this folder). Books: <rs2_state_dir>/paper_books (paths.py). Log: cache/paper_books.log.
# Remove with: .\register_paper_books_task.ps1 -Remove
param([switch]$Remove)
$name = "RS2-Paper-Books"
if ($Remove) { Unregister-ScheduledTask -TaskName $name -Confirm:$false; "removed"; return }
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$root = Split-Path -Parent (Split-Path -Parent $here)
$principal = New-ScheduledTaskPrincipal -UserId "$env:USERDOMAIN\$env:USERNAME" -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -MultipleInstances IgnoreNew -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable
$action = New-ScheduledTaskAction -Execute "wscript.exe" -Argument "`"$here\run_paper_books_hidden.vbs`"" -WorkingDirectory $root
Register-ScheduledTask -TaskName $name -Action $action -Trigger (New-ScheduledTaskTrigger -Daily -At "09:00") -Settings $settings `
    -Principal $principal -Force `
    -Description "Paper books, daily: archive and verify new screener GitHub runs, forward_ledger (A0), universe prices, m3o_engine; commit and push rs2-state paper_books/. Exit 1 on any failed step (cache/paper_books.log). tools/paper_books/run_monthly.py" | Out-Null
"registered"
