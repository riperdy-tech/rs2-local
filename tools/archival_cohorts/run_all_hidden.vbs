' Runs the four cohorts' valuations (cohort_run.py run) one after another with no console window: the RS2-Cohort-Run scheduled
' task's wrapper (PREREG_cohorts_nextq v1.0, 2026-11-11). The repository root is derived from this script's location
' (tools/archival_cohorts -> two levels up). Log: cache/cohort_run_task.log (append). Each cohort's run waits for its packets
' (j2_run's rounds). A stop (exit 7: crash, engine_defect, unpinned cost of equity; exit 5: cache/j2_yield.flag) ends that cohort's
' pass and the next cohort starts, which stops the same way where the cause is shared. A filled slot is never redone.
Dim fso, root, py, script, logFile, cmd, t
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(fso.GetParentFolderName(fso.GetParentFolderName(WScript.ScriptFullName)))
py = "C:\Program Files\Python312\python.exe"
script = fso.BuildPath(fso.BuildPath(fso.BuildPath(root, "tools"), "archival_cohorts"), "cohort_run.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "cohort_run_task.log")
cmd = "cmd /c cd /d """ & root & """"
For Each t In Array("2025-10-01", "2025-11-20", "2026-05-20", "2026-08-20")
    cmd = cmd & " & echo === " & t & " >> """ & logFile & """ & """ & py & """ -u """ & script & """ run --t " & t & " >> """ & _
          logFile & """ 2>&1"
Next
CreateObject("WScript.Shell").Run cmd, 0, False
