Set shell = CreateObject("WScript.Shell")
Set fso = CreateObject("Scripting.FileSystemObject")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
mainLauncher = projectDir & "\Run_DBD_Autoclicker_Bloodweb.vbs"

If Not fso.FileExists(mainLauncher) Then
    MsgBox "Main launcher not found: " & mainLauncher, 16, "DBD Autoclicker Bloodweb"
    WScript.Quit 1
End If

shell.Run """" & mainLauncher & """", 0, False
