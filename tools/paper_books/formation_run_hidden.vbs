' Runs formation_run.py (the monthly AI-book formation's qwen_c runs, resumable) with no console window and waits for it, so the
' scheduled task stays "running" and its repeat starts no second copy (IgnoreNew plus formation_run's own runner.lock).
' Usage: wscript.exe formation_run_hidden.vbs <formation date, e.g. 2026-11-30>
' Exits at once when cache\paper_books\formation\finished_<date>.flag exists. Paths derive from this script's own folder; output goes to
' cache\paper_books\formation\runner.out / runner.err.
Dim fso, sh, here, root, py, stateDir, T, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count < 1 Then WScript.Quit 2
T = WScript.Arguments(0)
here = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(fso.GetParentFolderName(here))
py = "C:\Program Files\Python312\python.exe"

stateDir = fso.BuildPath(root, "cache")
If Not fso.FolderExists(stateDir) Then fso.CreateFolder stateDir
stateDir = fso.BuildPath(stateDir, "paper_books")
If Not fso.FolderExists(stateDir) Then fso.CreateFolder stateDir
stateDir = fso.BuildPath(stateDir, "formation")
If Not fso.FolderExists(stateDir) Then fso.CreateFolder stateDir

If fso.FileExists(fso.BuildPath(stateDir, "finished_" & T & ".flag")) Then WScript.Quit 0

sh.Environment("Process")("PYTHONIOENCODING") = "utf-8"
cmd = "cmd /c """"" & py & """ -u """ & fso.BuildPath(here, "formation_run.py") & """ " & T & _
      " >> """ & fso.BuildPath(stateDir, "runner.out") & """ 2>> """ & fso.BuildPath(stateDir, "runner.err") & """"""
WScript.Quit sh.Run(cmd, 0, True)
