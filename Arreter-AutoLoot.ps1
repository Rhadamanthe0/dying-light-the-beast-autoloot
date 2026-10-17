$ErrorActionPreference = 'Stop'
$taskEvidence = Join-Path $PSScriptRoot 'evidence\autoloot5m'
New-Item -ItemType Directory -Path $taskEvidence -Force | Out-Null
Set-Content -LiteralPath (Join-Path $taskEvidence 'stop.request') -Value 'user stop' -Encoding utf8
Write-Host 'Arret demande. La fouille en cours se termine avant le retrait.'
