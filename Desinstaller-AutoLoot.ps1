$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'AutoLoot-Common.ps1')
Stop-AutoLootInstallation $PSScriptRoot
$taskPrevious = Get-AutoLootPreviousRoot
if ($taskPrevious -and $taskPrevious -eq $PSScriptRoot) {
    Remove-Item -LiteralPath (Get-AutoLootStartupPath)
}
Write-Host 'Demarrage automatique retire. Vous pouvez supprimer ce dossier.'
