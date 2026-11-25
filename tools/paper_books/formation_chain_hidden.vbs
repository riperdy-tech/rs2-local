' Runs one pass of formation_chain.py (the month-end formation on the cloud reader: decide, packets, read, freeze, books file) with no
' console window and waits for it, so the scheduled task stays "running" and its repeat starts no second copy (IgnoreNew).
' Usage: wscript.exe formation_chain_hidden.vbs <formation date, e.g. 2026-11-30>
' Exits at once when cache\paper_books\formation\chain_published_<date>.flag exists. Paths derive from this script's own folder; output goes
' to cache\paper_books\formation\chain.out / chain.err of the tree this script is in (the site worker's tree).
Dim fso, sh, here, root, py, stateDir, T, cmd, d
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
If WScript.Arguments.Count < 1 Then WScript.Quit 2
T = WScript.Arguments(0)
here = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(fso.GetParentFolderName(here))
py = "C:\Program Files\Python312\python.exe"
stateDir = root
For Each d In Array("cache", "paper_books", "formation")
    stateDir = fso.BuildPath(stateDir, d)
    If Not fso.FolderExists(stateDir) Then fso.CreateFolder stateDir
Next
If fso.FileExists(fso.BuildPath(stateDir, "chain_published_" & T & ".flag")) Then WScript.Quit 0
sh.Environment("Process")("PYTHONIOENCODING") = "utf-8"
sh.CurrentDirectory = root
cmd = "cmd /c """"" & py & """ -u """ & fso.BuildPath(here, "formation_chain.py") & """ " & T & _
      " >> """ & fso.BuildPath(stateDir, "chain.out") & """ 2>> """ & fso.BuildPath(stateDir, "chain.err") & """"""
WScript.Quit sh.Run(cmd, 0, True)
