' Runs news_watch.py morning (news on the analysed stocks: gather from SearXNG, the reader's check, warnings, the site files) with no
' console window and waits for it, so the scheduled task stays "running" and starts no second copy (IgnoreNew plus news_watch's own
' cache\gemini_site\news\news.lock). Paths derive from this script's folder; output goes to cache\gemini_site\news\morning.out / morning.err.
Dim fso, sh, here, root, py, newsDir, cmd, d
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")
here = fso.GetParentFolderName(WScript.ScriptFullName)
root = fso.GetParentFolderName(fso.GetParentFolderName(here))
py = "C:\Program Files\Python312\python.exe"
newsDir = root
For Each d In Array("cache", "gemini_site", "news")
    newsDir = fso.BuildPath(newsDir, d)
    If Not fso.FolderExists(newsDir) Then fso.CreateFolder newsDir
Next
sh.Environment("Process")("PYTHONIOENCODING") = "utf-8"
cmd = "cmd /c """"" & py & """ -u """ & fso.BuildPath(here, "news_watch.py") & """ morning" & _
      " >> """ & fso.BuildPath(newsDir, "morning.out") & """ 2>> """ & fso.BuildPath(newsDir, "morning.err") & """"""
WScript.Quit sh.Run(cmd, 0, True)
