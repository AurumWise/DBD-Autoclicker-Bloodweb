Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwPath = projectDir & "\.venv\Scripts\pythonw.exe"
mainPath = projectDir & "\main.py"

If Not fso.FileExists(pythonwPath) Then
    MsgBox "Не найден Python в .venv: " & pythonwPath, 16, "DBD Bloodweb Bot"
    WScript.Quit 1
End If

If Not fso.FileExists(mainPath) Then
    MsgBox "Не найден main.py: " & mainPath, 16, "DBD Bloodweb Bot"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectDir
shell.Run """" & pythonwPath & """ """ & mainPath & """", 0, False
