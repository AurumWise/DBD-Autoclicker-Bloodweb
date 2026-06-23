Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
packagePath = projectDir & "\package.json"

If Not fso.FileExists(packagePath) Then
    MsgBox "package.json not found: " & packagePath, 16, "DBD Autoclicker Bloodweb"
    WScript.Quit 1
End If

If Not fso.FolderExists(projectDir & "\.venv") Then
    MsgBox ".venv folder not found. Python backend cannot start.", 16, "DBD Autoclicker Bloodweb"
    WScript.Quit 1
End If

If Not fso.FolderExists(projectDir & "\node_modules") Then
    MsgBox "node_modules folder not found. Run npm.cmd install in the project folder first.", 16, "DBD Autoclicker Bloodweb"
    WScript.Quit 1
End If

shell.CurrentDirectory = projectDir
shell.Run "cmd /c npm.cmd run start:electron", 0, False
