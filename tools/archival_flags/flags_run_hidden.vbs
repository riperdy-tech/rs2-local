' Runs flags_run.py run with no console window: the RS2-Flags-Run scheduled task's wrapper (PREREG B3b v1.0, amendment 1). The repository
' root is derived from this script's location (tools/archival_flags -> two levels up). Log: cache/flags_run_task.log (append). The pass
' is resumable and holds its own single-instance lock, so a second start (the at-logon trigger after a reboot) is safe.
Dim fso, root, py, script, logFile, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
py = "C:\Program Files\Python312\python.exe"
script = fso.BuildPath(fso.BuildPath(fso.BuildPath(root, "tools"), "archival_flags"), "flags_run.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "flags_run_task.log")
cmd = "cmd /c cd /d """ & root & """ & """ & py & """ -u """ & script & """ run >> """ & logFile & """ 2>&1"
WScript.Quit CreateObject("WScript.Shell").Run(cmd, 0, True)
