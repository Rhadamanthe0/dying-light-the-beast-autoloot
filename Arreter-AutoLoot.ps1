$ErrorActionPreference = 'Stop'
$taskEvidence = Join-Path $PSScriptRoot 'evidence\autoloot5m'
New-Item -ItemType Directory -Path $taskEvidence -Force | Out-Null
$taskStatusPath = Join-Path $taskEvidence 'status.json'
$taskHost = $null
try {
    if (Test-Path -LiteralPath $taskStatusPath -PathType Leaf) {
        $taskState = Get-Content -LiteralPath $taskStatusPath -Raw | ConvertFrom-Json
        if ($taskState.host_pid -gt 0) {
            $taskCandidate = Get-Process -Id $taskState.host_pid -ErrorAction SilentlyContinue
            # PowerShell 7 can decode JSON dates as DateTime; Windows PowerShell keeps strings.
            $taskStatusTime = if ($taskState.updated_at_utc -is [DateTime]) {
                $taskState.updated_at_utc.ToUniversalTime()
            } else {
                [DateTimeOffset]::Parse([string]$taskState.updated_at_utc, [Globalization.CultureInfo]::InvariantCulture).UtcDateTime
            }
            if ($taskCandidate -and $taskCandidate.ProcessName -like 'python*' -and $taskCandidate.StartTime.ToUniversalTime() -le $taskStatusTime) {
                # Retain a handle to this process identity before requesting stop.
                $taskCandidate.Handle | Out-Null
                $taskHost = $taskCandidate
            }
        }
    }
} catch {
    Write-Host 'Etat en cours de lecture : la demande d arret sera tout de meme enregistree.'
}
Set-Content -LiteralPath (Join-Path $taskEvidence 'stop.request') -Value 'user stop' -Encoding utf8
if ($taskHost) {
    Write-Host 'Arret en cours. La fouille en cours se termine avant le retrait.'
    if (-not $taskHost.WaitForExit(30000)) {
        Write-Host 'Arret encore en cours apres 30 secondes. Attendre avant de relancer ; aucun processus n a ete force a s arreter.'
        exit 1
    }
    Write-Host 'AutoLoot arrete. Vous pouvez le relancer ou mettre le dossier a jour.'
} else {
    Write-Host 'Demande d arret enregistree. Aucun hote actif identifie ; un demarrage en cours sera annule.'
}
