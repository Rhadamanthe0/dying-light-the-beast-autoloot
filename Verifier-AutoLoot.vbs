Option Explicit
Dim shell, files, root, command, result
Set shell = CreateObject("WScript.Shell")
Set files = CreateObject("Scripting.FileSystemObject")
root = files.GetParentFolderName(WScript.ScriptFullName)
command = """" & shell.ExpandEnvironmentStrings("%SystemRoot%") & "\System32\WindowsPowerShell\v1.0\powershell.exe"" -NoLogo -NoProfile -NonInteractive -ExecutionPolicy Bypass -File """ & root & "\AutoLoot-Entry.ps1"" -Action Verifier"
result = shell.Run(command, 0, True)
If result = 0 Then
    shell.Popup "Controles hors jeu reussis.", 0, "Better AutoLoot", 64
Else
    shell.Popup "Operation non terminee. Journal : " & root & "\evidence\Verifier-AutoLoot.log", 0, "Better AutoLoot", 16
End If
WScript.Quit result
