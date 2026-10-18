Option Explicit
Dim shell, files, root, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
command = """" & shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & root & "\tools\manage.ps1"" -Action Install"
result = shell.Run(command, 0, True)
If result = 0 Then
    shell.Popup "Installation complete. AutoLoot is now automatic. Keep this folder in place.", 0, "Better AutoLoot", 64
Else
    shell.Popup "Operation failed. See: " & root & "\evidence\Install-AutoLoot.log", 0, "Better AutoLoot", 16
End If
WScript.Quit result
