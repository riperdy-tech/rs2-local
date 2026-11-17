' Runs gemini_ondemand.py --arm sonnet work (the screener list analysed with Claude Sonnet in place of the local model, published to stockpeak.net) with no
' console window and waits for it, so the scheduled task stays "running" and its repeat starts no second copy (IgnoreNew plus the
' worker's own cache\gemini_site\worker_sonnet.lock). Paths derive from this script's folder; output goes to cache\gemini_site\worker_sonnet.out / worker_sonnet.err.
Dim fso, sh, here, root, py, siteDir, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(fso.GetParentFolderName(here))
py = "C:\Program Files\Python312\python.exe"
siteDir = fso.BuildPath(fso.BuildPath(root, "cache"), "gemini_site")
If Not fso.FolderExists(fso.BuildPath(root, "cache")) Then fso.CreateFolder fso.BuildPath(root, "cache")
If Not fso.FolderExists(siteDir) Then fso.CreateFolder siteDir
sh.Environment("Process")("PYTHONIOENCODING") = "utf-8"
cmd = "cmd /c """"" & py & """ -u """ & fso.BuildPath(here, "gemini_ondemand.py") & """ --arm sonnet work" & _
      " >> """ & fso.BuildPath(siteDir, "worker_sonnet.out") & """ 2>> """ & fso.BuildPath(siteDir, "worker_sonnet.err") & """"""
WScript.Quit sh.Run(cmd, 0, True)
