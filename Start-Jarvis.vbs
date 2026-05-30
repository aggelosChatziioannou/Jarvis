' Start-Jarvis.vbs
'
' Launches the source-installed Jarvis with all our customisations
' (Chatterbox voice clone, fast-path matcher, 7 MCPs, Whisper large-v3)
' with NO visible console window.
'
' Double-click this file OR use the desktop shortcut that points to it.
'
' Sets the required environment for the child Python process:
'   - PYTHONPATH so `import desktop_app` resolves
'   - OLLAMA_KEEP_ALIVE so models stay resident
'   - PYTHONIOENCODING so Greek text in logs doesn't crash on cp1252
'
' Failure modes covered:
'   - Missing venv pythonw.exe -> visible MsgBox instead of silent no-op
'   - Crash during boot       -> captured to a log file under LOCALAPPDATA
'                                so you can read the traceback after the fact

Option Explicit

Dim objShell, objFSO, repoDir, venvPy, logDir, logPath, cmdLine
Set objShell = CreateObject("WScript.Shell")
Set objFSO   = CreateObject("Scripting.FileSystemObject")

repoDir = "C:\Users\aggel\Jarvis-src"
venvPy  = repoDir & "\.venv\Scripts\pythonw.exe"

' --- Path validation -------------------------------------------------------
If Not objFSO.FileExists(venvPy) Then
    MsgBox "Jarvis venv not found at:" & vbCrLf & venvPy & vbCrLf & vbCrLf & _
           "Rebuild the virtualenv (python -m venv .venv && pip install -r requirements.txt) " & _
           "or update Start-Jarvis.vbs with the correct path.", _
           vbCritical, "Jarvis startup"
    WScript.Quit 1
End If

' --- Crash log location ----------------------------------------------------
' Use %LOCALAPPDATA%\Jarvis so logs survive across launches without polluting
' the repo root. The folder is created on first run.
logDir = objShell.ExpandEnvironmentStrings("%LOCALAPPDATA%") & "\Jarvis"
If Not objFSO.FolderExists(logDir) Then
    objFSO.CreateFolder logDir
End If
logPath = logDir & "\jarvis_startup.log"

' --- Build cmd line --------------------------------------------------------
' pythonw.exe has no console of its own. Without the >..\jarvis_startup.log
' redirect, any boot-time Python traceback would vanish into the void.
cmdLine = "cmd /c " & _
    "powershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File """ & repoDir & "\scripts\kill-jarvis.ps1"" & " & _
    "set PYTHONPATH=" & repoDir & "\src" & " && " & _
    "set PYTHONIOENCODING=utf-8 && " & _
    "set OLLAMA_KEEP_ALIVE=-1 && " & _
    "set CT2_CUDA_TRUE_FP16_GEMM=0 && " & _
    "cd /d """ & repoDir & """ && " & _
    """" & venvPy & """ -m desktop_app > """ & logPath & """ 2>&1"

' CT2_CUDA_TRUE_FP16_GEMM=0 forces CTranslate2 to accumulate FP16 GEMM ops
' in FP32. Without it, deep Whisper transformer layers can underflow on
' quiet input (e.g. our PD200X dynamic mic at 6-12") and produce unstable
' language token scores — directly responsible for Greek being detected as
' French in the original failure case. Belt-and-suspenders alongside the
' int8_float16 compute type which already side-steps FP16 GEMM for weights.

' Run("command", windowStyle, waitForCompletion)
'   windowStyle 0 = hidden, no taskbar, no console flash
'   waitForCompletion False = launch and return
objShell.Run cmdLine, 0, False
