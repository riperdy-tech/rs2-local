' Runs tools/archival_k2/k2_run.py run with no console window (the RS2-K2-Run scheduled task's wrapper).
' The repository root is derived from this script's location (tools/archival_k2 -> two levels up); nothing is hardcoded
' but the interpreter. Log: cache/k2_run_task.log (append).
Dim fso, root, py, script, logFile, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
py = "C:\Program Files\Python312\python.exe"
script = fso.BuildPath(fso.BuildPath(fso.BuildPath(root, "tools"), "archival_k2"), "k2_run.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "k2_run_task.log")
cmd = "cmd /c cd /d """ & root & """ && """ & py & """ -u """ & script & """ run >> """ & logFile & """ 2>&1"
CreateObject("WScript.Shell").Run cmd, 0, False
