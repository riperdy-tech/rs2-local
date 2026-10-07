' Run by the scheduled task RS2-Gate2-Replay (register_gate2_task.ps1).  Starts the gate-2 replay runner with NO window and waits for it, so the task stays "running" and its 15-minute
' repeat starts no second copy (and the runner's own runner.lock refuses a second one anyway).
'   wscript launch_gate2.vbs <mode: pilot|full|masked> <state dir>
' It lives in rebuild_harness\gate2 of the gate-2 repository; the repository root is two folders up, derived from this file's own location (no absolute path to the repository).
' Why a task and not a Claude session: on 2026-10-06 a Claude desktop update closed every process started under the app.  The run state is under the state dir
' (stocks-workspace\data\gate2), never %TEMP%.  The runner starts and stops the Muse llama-server itself and only when the GPU is free.
Dim sh, fso, here, repo, py, mode, state, q, cmd, rc
Set sh = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")
q = Chr(34)
here = fso.GetParentFolderName(WScript.ScriptFullName)
repo = fso.GetParentFolderName(fso.GetParentFolderName(here))
mode = "pilot"
If WScript.Arguments.Count > 0 Then mode = WScript.Arguments(0)
If WScript.Arguments.Count > 1 Then
    state = WScript.Arguments(1)
Else
    WScript.Quit 2
End If
If Not fso.FolderExists(state) Then
    Dim parts, i, cur
    parts = Split(state, "\")
    cur = parts(0)
    For i = 1 To UBound(parts)
        cur = cur & "\" & parts(i)
        If Not fso.FolderExists(cur) Then fso.CreateFolder(cur)
    Next
End If
py = q & "C:\Program Files\Python312\python.exe" & q & " -u -m rebuild_harness.gate2.runner --mode " & mode & " --state-dir " & q & state & q
cmd = "cmd /c set PYTHONIOENCODING=utf-8&& " & py & " >> " & q & state & "\runner.out" & q & " 2>> " & q & state & "\runner.err" & q
sh.CurrentDirectory = repo
rc = sh.Run(cmd, 0, True)
WScript.Quit rc
