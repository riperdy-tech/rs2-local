' Runs the S1b then the S1 valuations with no console window (the RS2-Street-Run scheduled task's wrapper, 2026-11-09):
'   street_run.py run --dir archival_2025-10-01_pit   (S1b: K2's packets, point-in-time cost of equity at 2025-10-01)
'   street_run.py run                                  (S1: the 2026-06-15 pool)
' The repository root is derived from this script's location (tools/archival_street -> two levels up); nothing is hardcoded
' but the interpreter. Log: cache/street_run_task.log (append). The S1 pass starts only when the S1b pass exits 0.
Dim fso, root, py, script, logFile, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
py = "C:\Program Files\Python312\python.exe"
script = fso.BuildPath(fso.BuildPath(fso.BuildPath(root, "tools"), "archival_street"), "street_run.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "street_run_task.log")
cmd = "cmd /c cd /d """ & root & """ && """ & py & """ -u """ & script & """ run --dir archival_2025-10-01_pit >> """ & logFile & _
      """ 2>&1 && """ & py & """ -u """ & script & """ run >> """ & logFile & """ 2>&1"
CreateObject("WScript.Shell").Run cmd, 0, False
