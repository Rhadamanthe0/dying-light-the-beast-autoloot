Option Explicit
Dim shell, files, root, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
command = """" & shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & root & "\tools\manage.ps1"" -Action Pause"
result = shell.Run(command, 0, True)
If result = 0 Then
    shell.Popup "AutoLoot is paused. Run Resume-AutoLoot.vbs to resume.", 0, "Better AutoLoot", 64
Else
    shell.Popup "Operation failed. See: " & root & "\evidence\Pause-AutoLoot.log", 0, "Better AutoLoot", 16
End If
WScript.Quit result
