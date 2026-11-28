' Runs daily_report.py send (the day's Telegram message: did every job run, the AI book, what it bought and sold) with no console window.
' Paths derive from this script's folder; output goes to cache\gemini_site\daily_report.out / daily_report.err.
Dim fso, sh, here, root, py, siteDir, cmd, d
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(fso.GetParentFolderName(here))
py = "C:\Program Files\Python312\python.exe"
siteDir = root
For Each d In Array("cache", "gemini_site")
    siteDir = fso.BuildPath(siteDir, d)
    If Not fso.FolderExists(siteDir) Then fso.CreateFolder siteDir
Next
sh.Environment("Process")("PYTHONIOENCODING") = "utf-8"
cmd = "cmd /c """"" & py & """ -u """ & fso.BuildPath(here, "daily_report.py") & """ send" & _
      " >> """ & fso.BuildPath(siteDir, "daily_report.out") & """ 2>> """ & fso.BuildPath(siteDir, "daily_report.err") & """"""
WScript.Quit sh.Run(cmd, 0, True)
