' Builds the four cohorts' packets (cohort_run.py packets) one after another with no console window: the RS2-Cohort-Packets scheduled
' task's wrapper (PREREG_cohorts_nextq, 2026-11-10). The repository root is derived from this script's location (tools/archival_cohorts
' -> two levels up). Log: cache/cohort_packets_task.log (append). A network failure stops that cohort's pass (resumable); the next runs.
Dim fso, root, py, script, logFile, cmd, t
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
py = "C:\Program Files\Python312\python.exe"
script = fso.BuildPath(fso.BuildPath(fso.BuildPath(root, "tools"), "archival_cohorts"), "cohort_run.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "cohort_packets_task.log")
cmd = "cmd /c cd /d """ & root & """"
For Each t In Array("2025-10-01", "2025-11-20", "2026-05-20", "2026-08-20")
    cmd = cmd & " & echo === " & t & " >> """ & logFile & """ & """ & py & """ -u """ & script & """ packets --t " & t & " >> """ & _
          logFile & """ 2>&1"
Next
CreateObject("WScript.Shell").Run cmd, 0, False
