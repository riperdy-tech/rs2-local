' Runs control_agent.py with no console window (scheduled task wrapper).
' Window style 0 = hidden; log redirection unchanged.
CreateObject("WScript.Shell").Run "cmd /c """"C:\Program Files\Python312\python.exe"" ""C:\Users\riper\Downloads\RS2 Local\control_agent.py"" >> ""C:\Users\riper\Downloads\RS2 Local\cache\control_agent_task.log"" 2>&1""", 0, False
