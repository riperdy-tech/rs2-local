' Runs run_monthly.py with no console window (RS2-Paper-Books task wrapper), waits for it, and returns its exit code, so the
' task's Last Run Result shows a failed run as nonzero. Paths derive from this script's own folder. run_monthly.py logs to
' cache/paper_books.log itself; anything it prints before it can log (an interpreter that will not start) goes to
' cache/paper_books_task.log.
Dim fso, here, root, py, script, logFile, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
here = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(fso.GetParentFolderName(here))

py = "C:\Program Files\Python312\python.exe"
script = fso.BuildPath(here, "run_monthly.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "paper_books_task.log")

cmd = "cmd /c """"" & py & """ -u """ & script & """ >> """ & logFile & """ 2>&1"""
WScript.Quit CreateObject("WScript.Shell").Run(cmd, 0, True)
