' Runs control_agent.py with no console window (scheduled task wrapper).
' Window style 0 = hidden; log redirection unchanged.
'
' The repo root is derived from this script's own location rather than hardcoded. It was
' hardcoded to C:\Users\riper\Downloads\RS2 Local until 2026-09-22, which meant the folder move
' silently broke the scheduled task: wscript would exit 0 having launched a cmd that failed to
' find the interpreter target, so the agent would simply stop heartbeating with no error anywhere
' the operator would look.
Dim fso, root, py, agent, logFile, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
root = fso.GetParentFolderName(WScript.ScriptFullName)

py = "C:\Program Files\Python312\python.exe"
agent = fso.BuildPath(root, "control_agent.py")
logFile = fso.BuildPath(fso.BuildPath(root, "cache"), "control_agent_task.log")

cmd = "cmd /c """"" & py & """ """ & agent & """ >> """ & logFile & """ 2>&1"""
CreateObject("WScript.Shell").Run cmd, 0, False
