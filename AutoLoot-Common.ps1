$ErrorActionPreference = 'Stop'

function Get-AutoLootWatcher([string]$Root) {
    $path = Join-Path $Root 'evidence\autoloot5m\watch-status.json'
    try {
        $state = Get-Content -LiteralPath $path -Raw | ConvertFrom-Json
        $process = Get-Process -Id ([int]$state.host_pid) -ErrorAction Stop
        $stamp = if ($state.updated_at_utc -is [DateTime]) { $state.updated_at_utc.ToUniversalTime() } else {
            [DateTimeOffset]::Parse([string]$state.updated_at_utc, [Globalization.CultureInfo]::InvariantCulture).UtcDateTime
        }
        if ($process.ProcessName -notlike 'python*' -or $process.StartTime.ToUniversalTime() -gt $stamp) { return $null }
        $process.Handle | Out-Null
        return $process
    } catch { return $null }
}

function Stop-AutoLootInstallation([string]$Root) {
    $evidence = Join-Path $Root 'evidence\autoloot5m'
    New-Item -ItemType Directory -Path $evidence -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $evidence 'watch.pause') -Value 'installation stopped' -Encoding utf8
    $watcher = Get-AutoLootWatcher $Root
    Set-Content -LiteralPath (Join-Path $evidence 'watch.stop') -Value 'installation stopped' -Encoding utf8
    $LASTEXITCODE = 0
    & (Join-Path $PSScriptRoot 'Arreter-AutoLoot.ps1') -Root $Root
    if (-not $? -or $LASTEXITCODE -ne 0) { throw 'Le ramassage termine encore son arret. Installation ou retrait annule.' }
    if ($watcher -and -not $watcher.WaitForExit(30000)) { throw 'La surveillance termine encore son arret. Reessayer apres sa fermeture.' }
}

function Get-AutoLootStartupPath {
    Join-Path ([Environment]::GetFolderPath('Startup')) 'Better AutoLoot.lnk'
}

function Get-AutoLootPreviousRoot {
    $path = Get-AutoLootStartupPath
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $root = $shortcut.WorkingDirectory
    if (-not $root -or $shortcut.Description -ne 'DLTB AutoLoot automatic startup v1' -or
        $shortcut.TargetPath -ne (Join-Path $root '.venv\Scripts\pythonw.exe') -or
        $shortcut.Arguments -ne ('"' + (Join-Path $root 'tools\autoloot_watch.py') + '" --live')) {
        throw 'Un raccourci Better AutoLoot non reconnu existe deja dans Demarrage. Il n a pas ete modifie.'
    }
    return $root
}

function Register-AutoLootStartup([string]$Root) {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Get-AutoLootStartupPath))
    $shortcut.TargetPath = Join-Path $Root '.venv\Scripts\pythonw.exe'
    $shortcut.Arguments = '"' + (Join-Path $Root 'tools\autoloot_watch.py') + '" --live'
    $shortcut.WorkingDirectory = $Root
    $shortcut.Description = 'DLTB AutoLoot automatic startup v1'
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}
