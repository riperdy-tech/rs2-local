' Runs formation_value.py (F10: the menu valuations of one formation's A0 book, resumable) with no console window and waits for it, so
' the scheduled task stays "running" and its repeat starts no second copy (IgnoreNew plus formation_value's own value.lock).
' Usage: wscript.exe formation_value_hidden.vbs <formation date, e.g. 2026-11-30>
' Exits at once when cache\paper_books\formation\value_finished_<date>.flag exists. Paths derive from this script's own folder; output
' goes to cache\paper_books\formation\value.out / value.err.
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

If fso.FileExists(fso.BuildPath(stateDir, "value_finished_" & T & ".flag")) Then WScript.Quit 0

sh.Environment("Process")("PYTHONIOENCODING") = "utf-8"
cmd = "cmd /c """"" & py & """ -u """ & fso.BuildPath(here, "formation_value.py") & """ " & T & _
      " >> """ & fso.BuildPath(stateDir, "value.out") & """ 2>> """ & fso.BuildPath(stateDir, "value.err") & """"""
WScript.Quit sh.Run(cmd, 0, True)
