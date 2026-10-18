param([Parameter(Mandatory=$true)][ValidateSet('Installer','Lancer','Arreter','Verifier','Desinstaller')][string]$Action)
$ErrorActionPreference = 'Stop'
$taskLogDirectory = Join-Path $PSScriptRoot 'evidence'
New-Item -ItemType Directory -Path $taskLogDirectory -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $taskLogDirectory ($Action + '-AutoLoot.log')) -Force | Out-Null
try {
    & (Join-Path $PSScriptRoot ($Action + '-AutoLoot.ps1'))
    if (-not $?) { throw 'L operation a echoue.' }
} catch {
    Write-Output $_
    exit 1
} finally { Stop-Transcript | Out-Null }
