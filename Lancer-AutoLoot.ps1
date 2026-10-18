$ErrorActionPreference = 'Stop'
try {
$taskRoot = $PSScriptRoot
$taskPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Executer Installer-AutoLoot.cmd une premiere fois.' }
$taskEvidence = Join-Path $taskRoot 'evidence\autoloot5m'
New-Item -ItemType Directory -Path $taskEvidence -Force | Out-Null
$taskScript = Join-Path $taskRoot 'tools\autoloot_runtime.py'
$taskStamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$taskLaunchToken = [guid]::NewGuid().ToString('N')
$taskChild = Start-Process -FilePath $taskPython -ArgumentList @('-u', ('"' + $taskScript + '"'), '--live', '--launch-token', $taskLaunchToken) -WorkingDirectory $taskRoot -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $taskEvidence ($taskStamp + '-stdout.log')) -RedirectStandardError (Join-Path $taskEvidence ($taskStamp + '-stderr.log'))
$taskStatusPath = Join-Path $taskEvidence 'status.json'
$taskDeadline = [DateTime]::UtcNow.AddSeconds(30)
while ([DateTime]::UtcNow -lt $taskDeadline) {
    $taskState = $null
    try { if (Test-Path -LiteralPath $taskStatusPath) { $taskState = Get-Content -LiteralPath $taskStatusPath -Raw | ConvertFrom-Json } } catch { }
    if ($taskState -and $taskState.launch_token -eq $taskLaunchToken) {
        if ($taskState.running -and $taskState.phase -in @('active', 'running')) {
            Write-Host 'AutoLoot actif : rayon 5 m, passage toutes les 250 ms.'
            Write-Host 'Pour arreter : Arreter-AutoLoot.cmd.'
            exit 0
        }
        if ($taskState.phase -in @('error', 'game_closed', 'stopped')) {
            throw ('AutoLoot non actif : ' + $taskState.phase + ' ' + $taskState.message)
        }
    }
    $taskChild.Refresh()
    if ($taskChild.HasExited) {
        if ($taskChild.ExitCode -eq 2 -and $taskState -and $taskState.running -and $taskState.launch_token -ne $taskLaunchToken) {
            $taskExisting = Get-Process -Id $taskState.host_pid -ErrorAction SilentlyContinue
            if ($taskExisting -and $taskExisting.ProcessName -like 'python*') { Write-Host 'Une instance AutoLoot est deja active.'; exit 0 }
        }
        throw ('Demarrage impossible. Voir ' + $taskEvidence + ' et charger une partie avant de relancer.')
    }
    Start-Sleep -Milliseconds 100
}
throw ('Le demarrage reste en attente. Consulter ' + $taskStatusPath + '. Aucun processus force a s arreter.')
} catch {
    Write-Host ('AutoLoot : ' + $_.Exception.Message)
    exit 1
}
