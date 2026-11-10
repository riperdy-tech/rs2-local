' Builds the four next-quarter cohort pools (pool_cohort.py, target 125) one after another with no console window: the
' RS2-Cohort-Pools scheduled task's wrapper (PREREG_cohorts_nextq, 2026-11-10). The repository root is derived from this script's
' location (tools/archival_cohorts -> two levels up). Log: cache/cohort_pools_task.log (append). A pool that misses its target exits 2
' and the next one still runs: the shortfall is in that pool's counts.
Dim fso, root, py, script, logFile, cmd, t
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
py = "C:\Program Files\Python312\python.exe"
script = fso.BuildPath(fso.BuildPath(fso.BuildPath(root, "tools"), "archival_cohorts"), "pool_cohort.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "cohort_pools_task.log")
cmd = "cmd /c cd /d """ & root & """"
For Each t In Array("2025-10-01", "2025-11-20", "2026-05-20", "2026-08-20")
    cmd = cmd & " & echo === " & t & " >> """ & logFile & """ & """ & py & """ -u """ & script & """ --t " & t & " --target 125 >> """ & _
          logFile & """ 2>&1"
Next
CreateObject("WScript.Shell").Run cmd, 0, False
