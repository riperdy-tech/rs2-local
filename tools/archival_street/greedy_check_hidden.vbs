' Runs the decoding check (greedy_check.py run) with no console window (the RS2-Greedy-Check scheduled task's wrapper, 2026-11-10).
' The repository root is derived from this script's location (tools/archival_street -> two levels up); nothing is hardcoded but the
' interpreter. Log: cache/greedy_check_task.log (append). The score phase runs when the run phase exits 0.
Dim fso, root, py, script, logFile, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
py = "C:\Program Files\Python312\python.exe"
script = fso.BuildPath(fso.BuildPath(fso.BuildPath(root, "tools"), "archival_street"), "greedy_check.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "greedy_check_task.log")
cmd = "cmd /c cd /d """ & root & """ && """ & py & """ -u """ & script & """ run >> """ & logFile & _
      """ 2>&1 && """ & py & """ -u """ & script & """ score >> """ & logFile & """ 2>&1"
CreateObject("WScript.Shell").Run cmd, 0, False
