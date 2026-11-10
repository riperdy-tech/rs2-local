' Runs the prompt v13 replay (v13_replay.py run) with no console window (the RS2-V13-Replay scheduled task's wrapper, 2026-11-10).
' The repository root is derived from this script's location (tools/archival_street -> two levels up); nothing is hardcoded but the
' interpreter. Log: cache/v13_replay_task.log (append).
Dim fso, root, py, script, logFile, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
py = "C:\Program Files\Python312\python.exe"
script = fso.BuildPath(fso.BuildPath(fso.BuildPath(root, "tools"), "archival_street"), "v13_replay.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "v13_replay_task.log")
cmd = "cmd /c cd /d """ & root & """ && """ & py & """ -u """ & script & """ run >> """ & logFile & """ 2>&1"
CreateObject("WScript.Shell").Run cmd, 0, False
