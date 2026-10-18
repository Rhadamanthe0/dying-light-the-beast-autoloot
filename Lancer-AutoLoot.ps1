$ErrorActionPreference = 'Stop'
. (Join-Path $PSScriptRoot 'AutoLoot-Common.ps1')
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\pythonw.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Executer Installer-AutoLoot.vbs en premier.' }
$taskEvidence = Join-Path $PSScriptRoot 'evidence\autoloot5m'
New-Item -ItemType Directory -Path $taskEvidence -Force | Out-Null
$taskWatcher = Get-AutoLootWatcher $PSScriptRoot
$taskWatcherClosing = Test-Path -LiteralPath (Join-Path $taskEvidence 'watch.stop')
if ($taskWatcher) {
    try {
        $taskPreviousState = Get-Content -LiteralPath (Join-Path $taskEvidence 'watch-status.json') -Raw | ConvertFrom-Json
        if ($taskPreviousState.host_pid -eq $taskWatcher.Id -and $taskPreviousState.running -eq $false) { $taskWatcherClosing = $true }
    } catch { }
}
if ($taskWatcher -and $taskWatcherClosing) {
    if (-not $taskWatcher.WaitForExit(30000)) { throw 'La surveillance termine encore son arret.' }
    $taskWatcher = $null
}
Set-Content -LiteralPath (Join-Path $taskEvidence 'watch.resume') -Value ([guid]::NewGuid().ToString('N')) -Encoding utf8
Remove-Item -LiteralPath (Join-Path $taskEvidence 'watch.pause') -Force -ErrorAction SilentlyContinue
if ($taskWatcher) { Write-Host 'Surveillance automatique reprise.'; return }
Remove-Item -LiteralPath (Join-Path $taskEvidence 'watch.stop') -Force -ErrorAction SilentlyContinue
$taskToken = [guid]::NewGuid().ToString('N')
$taskArguments = '"' + (Join-Path $PSScriptRoot 'tools\autoloot_watch.py') + '" --live --launch-token ' + $taskToken
$taskChild = Start-Process -FilePath $taskPython -ArgumentList $taskArguments -WorkingDirectory $PSScriptRoot -WindowStyle Hidden -PassThru
$taskDeadline = [DateTime]::UtcNow.AddSeconds(20)
do {
    $taskState = $null
    try {
        $taskState = Get-Content -LiteralPath (Join-Path $taskEvidence 'watch-status.json') -Raw | ConvertFrom-Json
    } catch { }
    if ($taskState -and $taskState.launch_token -eq $taskToken -and $taskState.phase -eq 'error') {
        throw ('Echec de la surveillance : ' + $taskState.last_error)
    }
    if ($taskState -and $taskState.launch_token -eq $taskToken -and $taskState.running -and $taskState.phase -ne 'starting') {
        Write-Host 'Surveillance active : detection du jeu toutes les 10 secondes, ramassage a 2 m toutes les 100 ms.'
        return
    }
    Start-Sleep -Milliseconds 200
} while ([DateTime]::UtcNow -lt $taskDeadline)
throw 'La surveillance n a pas confirme son demarrage. Consulter evidence\autoloot5m\watch-status.json et watch.log.'
