param(
    [ValidateSet('Install', 'Prepare', 'Configure', 'Pause', 'Resume', 'Uninstall')][string]$Action,
    [string]$Root = (Split-Path -Parent $PSScriptRoot),
    [string]$StatePath,
    [switch]$NoAutoStart
)
$ErrorActionPreference = 'Stop'

function Get-AutoLootProcess([string]$StatusPath) {
    if (-not (Test-Path -LiteralPath $StatusPath -PathType Leaf)) { return $null }
    try {
        $state = Get-Content -LiteralPath $StatusPath -Raw | ConvertFrom-Json
        $process = Get-Process -Id ([int]$state.host_pid) -ErrorAction Stop
        $stamp = if ($state.updated_at_utc -is [DateTime]) { $state.updated_at_utc.ToUniversalTime() } else {
            [DateTimeOffset]::Parse([string]$state.updated_at_utc, [Globalization.CultureInfo]::InvariantCulture).UtcDateTime
        }
        if ($process.ProcessName -notlike 'python*' -or $process.StartTime.ToUniversalTime() -gt $stamp) { return $null }
        # Retain this process identity before requesting a cooperative stop.
        $process.Handle | Out-Null
        return $process
    } catch { return $null }
}

function Get-AutoLootWatcher([string]$InstallationRoot) {
    Get-AutoLootProcess (Join-Path $InstallationRoot 'evidence\autoloot5m\watch-status.json')
}

function Pause-AutoLoot([string]$InstallationRoot) {
    $data = Join-Path $InstallationRoot 'evidence\autoloot5m'
    New-Item -ItemType Directory -Path $data -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $data 'watch.pause') -Value 'user pause' -Encoding utf8
    $worker = Get-AutoLootProcess (Join-Path $data 'status.json')
    Set-Content -LiteralPath (Join-Path $data 'stop.request') -Value 'user stop' -Encoding utf8
    if ($worker -and -not $worker.WaitForExit(30000)) {
        throw 'AutoLoot is still finishing an in-game call. Wait before retrying; no process was terminated.'
    }
    Write-Host 'AutoLoot paused. Any pending launch will also be cancelled.'
}

function Stop-AutoLootInstallation([string]$InstallationRoot) {
    $data = Join-Path $InstallationRoot 'evidence\autoloot5m'
    New-Item -ItemType Directory -Path $data -Force | Out-Null
    Set-Content -LiteralPath (Join-Path $data 'watch.pause') -Value 'installation stopped' -Encoding utf8
    $watcher = Get-AutoLootWatcher $InstallationRoot
    Set-Content -LiteralPath (Join-Path $data 'watch.stop') -Value 'installation stopped' -Encoding utf8
    Pause-AutoLoot $InstallationRoot
    if ($watcher -and -not $watcher.WaitForExit(30000)) {
        throw 'The watcher is still shutting down. Wait before retrying.'
    }
}

function Get-AutoLootStartupPath {
    Join-Path ([Environment]::GetFolderPath('Startup')) 'Better AutoLoot.lnk'
}

function Get-AutoLootPython([string]$InstallationRoot, [switch]$Windowed) {
    $name = if ($Windowed) { 'pythonw.exe' } else { 'python.exe' }
    $directory = if (Test-Path -LiteralPath (Join-Path $InstallationRoot 'runtime') -PathType Container) {
        'runtime'
    } else { '.venv\Scripts' }
    $python = Join-Path (Join-Path $InstallationRoot $directory) $name
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        throw ('Python runtime is missing: ' + $python + '. Reinstall Better AutoLoot.')
    }
    return $python
}

function Get-AutoLootPreviousRoot {
    $path = Get-AutoLootStartupPath
    if (-not (Test-Path -LiteralPath $path)) { return $null }
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut($path)
    $previous = $shortcut.WorkingDirectory
    if (-not $previous -or $shortcut.Description -ne 'DLTB AutoLoot automatic startup v1' -or
        $shortcut.TargetPath -notin @((Join-Path $previous '.venv\Scripts\pythonw.exe'), (Join-Path $previous 'runtime\pythonw.exe')) -or
        $shortcut.Arguments -ne ('"' + (Join-Path $previous 'tools\autoloot_watch.py') + '" --live')) {
        throw 'An unrecognized Better AutoLoot startup shortcut already exists. It was not changed.'
    }
    return $previous
}

function Register-AutoLootStartup([string]$InstallationRoot) {
    $shortcut = (New-Object -ComObject WScript.Shell).CreateShortcut((Get-AutoLootStartupPath))
    $shortcut.TargetPath = Get-AutoLootPython $InstallationRoot -Windowed
    $shortcut.Arguments = '"' + (Join-Path $InstallationRoot 'tools\autoloot_watch.py') + '" --live'
    $shortcut.WorkingDirectory = $InstallationRoot
    $shortcut.Description = 'DLTB AutoLoot automatic startup v1'
    $shortcut.WindowStyle = 7
    $shortcut.Save()
}

function Resume-AutoLoot([string]$InstallationRoot, [switch]$KeepPaused) {
    $python = Get-AutoLootPython $InstallationRoot -Windowed
    $data = Join-Path $InstallationRoot 'evidence\autoloot5m'
    New-Item -ItemType Directory -Path $data -Force | Out-Null
    $watcher = Get-AutoLootWatcher $InstallationRoot
    $closing = Test-Path -LiteralPath (Join-Path $data 'watch.stop')
    if ($watcher) {
        try {
            $previous = Get-Content -LiteralPath (Join-Path $data 'watch-status.json') -Raw | ConvertFrom-Json
            if ($previous.host_pid -eq $watcher.Id -and $previous.running -eq $false) { $closing = $true }
        } catch { }
    }
    if ($watcher -and $closing) {
        if (-not $watcher.WaitForExit(30000)) { throw 'The watcher is still shutting down.' }
        $watcher = $null
    }
    if ($KeepPaused) {
        Set-Content -LiteralPath (Join-Path $data 'watch.pause') -Value 'user pause preserved' -Encoding utf8
    } else {
        Set-Content -LiteralPath (Join-Path $data 'watch.resume') -Value ([guid]::NewGuid().ToString('N')) -Encoding utf8
        Remove-Item -LiteralPath (Join-Path $data 'watch.pause') -Force -ErrorAction SilentlyContinue
    }
    if ($watcher) {
        if ($KeepPaused) { Write-Host 'Watcher active. AutoLoot remains paused.' }
        else { Write-Host 'Automatic operation resumed.' }
        return
    }
    Remove-Item -LiteralPath (Join-Path $data 'watch.stop') -Force -ErrorAction SilentlyContinue
    $token = [guid]::NewGuid().ToString('N')
    $arguments = '"' + (Join-Path $InstallationRoot 'tools\autoloot_watch.py') + '" --live --launch-token ' + $token
    Start-Process -FilePath $python -ArgumentList $arguments -WorkingDirectory $InstallationRoot -WindowStyle Hidden | Out-Null
    $deadline = [DateTime]::UtcNow.AddSeconds(20)
    do {
        $state = $null
        $statusPath = Join-Path $data 'watch-status.json'
        try {
            if (Test-Path -LiteralPath $statusPath) { $state = Get-Content -LiteralPath $statusPath -Raw | ConvertFrom-Json }
        } catch { }
        if ($state -and $state.launch_token -eq $token -and $state.phase -eq 'error') {
            throw ('Watcher startup failed: ' + $state.last_error)
        }
        if ($state -and $state.launch_token -eq $token -and $state.running -and $state.phase -ne 'starting') {
            if ($KeepPaused) { Write-Host 'Watcher active. AutoLoot remains paused.' }
            else { Write-Host 'Watcher active: game detection every 10 seconds; looting within 2 m every 100 ms.' }
            return
        }
        Start-Sleep -Milliseconds 200
    } while ([DateTime]::UtcNow -lt $deadline)
    throw 'Watcher startup was not confirmed. See evidence\autoloot5m\watch-status.json and watch.log.'
}

function Prepare-AutoLoot([string]$InstallationRoot, [string]$InstallerStatePath, [switch]$SkipAutoStart) {
    if (-not $InstallerStatePath) { throw 'An installer state path is required.' }
    $previous = if (-not $SkipAutoStart) { Get-AutoLootPreviousRoot } else { $null }
    # Capture the user's choice before cooperative shutdown itself creates watch.pause.
    $keepPaused = Test-Path -LiteralPath (Join-Path $InstallationRoot 'evidence\autoloot5m\watch.pause')
    if ($previous -and $previous -ne $InstallationRoot -and (Test-Path -LiteralPath $previous -PathType Container)) {
        $keepPaused = $keepPaused -or (Test-Path -LiteralPath (Join-Path $previous 'evidence\autoloot5m\watch.pause'))
        Stop-AutoLootInstallation $previous
    }
    Stop-AutoLootInstallation $InstallationRoot
    @{ version = 1; root = [IO.Path]::GetFullPath($InstallationRoot); keep_paused = [bool]$keepPaused;
       no_auto_start = [bool]$SkipAutoStart } | ConvertTo-Json | Set-Content -LiteralPath $InstallerStatePath -Encoding utf8
}

function Configure-AutoLoot([string]$InstallationRoot, [string]$InstallerStatePath, [switch]$SkipAutoStart) {
    if (-not $InstallerStatePath -or -not (Test-Path -LiteralPath $InstallerStatePath -PathType Leaf)) {
        throw 'Installer preparation state is missing. Run the installer again.'
    }
    $state = Get-Content -LiteralPath $InstallerStatePath -Raw | ConvertFrom-Json
    if ($state.version -ne 1 -or $state.root -ne [IO.Path]::GetFullPath($InstallationRoot) -or
        $state.no_auto_start -ne [bool]$SkipAutoStart) { throw 'Installer preparation state does not match this installation.' }
    $python = Get-AutoLootPython $InstallationRoot
    & $python (Join-Path $InstallationRoot 'tools\autoloot_runtime.py') --dummy
    if ($LASTEXITCODE -ne 0) { throw 'Offline checks failed. See the installation log.' }
    if ($SkipAutoStart) {
        Write-Host 'Offline checks passed. Automatic startup is disabled; AutoLoot remains paused.'
        return
    }
    Register-AutoLootStartup $InstallationRoot
    Resume-AutoLoot $InstallationRoot -KeepPaused:([bool]$state.keep_paused)
    Write-Host 'Installation complete. AutoLoot will start automatically with your games and at Windows sign-in.'
}

function Install-AutoLoot([string]$InstallationRoot) {
    if (Test-Path -LiteralPath (Join-Path $InstallationRoot 'runtime') -PathType Container) {
        $installerState = Join-Path $InstallationRoot 'evidence\installer-state.json'
        Prepare-AutoLoot $InstallationRoot $installerState -SkipAutoStart:$NoAutoStart
        Configure-AutoLoot $InstallationRoot $installerState -SkipAutoStart:$NoAutoStart
        return
    }
    $previous = Get-AutoLootPreviousRoot
    if ($previous -and $previous -ne $InstallationRoot -and (Test-Path -LiteralPath $previous -PathType Container)) {
        Stop-AutoLootInstallation $previous
    }
    Stop-AutoLootInstallation $InstallationRoot
    $python = Join-Path $InstallationRoot '.venv\Scripts\python.exe'
    if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
        $basePython = $null
        foreach ($command in @('py', 'python')) {
            if (-not (Get-Command $command -ErrorAction SilentlyContinue)) { continue }
            $arguments = if ($command -eq 'py') { @('-3', '-c', 'import sys; print(sys.executable)') } else { @('-c', 'import sys; print(sys.executable)') }
            $candidate = (& $command @arguments | Select-Object -Last 1)
            if ($LASTEXITCODE -eq 0 -and $candidate -and (Test-Path -LiteralPath $candidate.Trim() -PathType Leaf)) {
                $basePython = $candidate.Trim(); break
            }
        }
        if (-not $basePython) { throw 'Install 64-bit Python 3.11 or newer from python.org, then retry.' }
        & $basePython -c 'import struct,sys; sys.exit(0 if sys.version_info >= (3,11) and struct.calcsize(chr(80))==8 else 1)'
        if ($LASTEXITCODE -ne 0) { throw '64-bit Python 3.11 or newer is required.' }
        & $basePython -m venv (Join-Path $InstallationRoot '.venv')
        if ($LASTEXITCODE -ne 0) { throw 'Could not create the Python environment.' }
    }
    & $python -m pip install --disable-pip-version-check -r (Join-Path $InstallationRoot 'requirements.txt')
    if ($LASTEXITCODE -ne 0) { throw 'Dependency installation failed.' }
    & $python (Join-Path $InstallationRoot 'tools\autoloot_runtime.py') --dummy
    if ($LASTEXITCODE -ne 0) { throw 'Offline checks failed. See the installation log.' }
    Register-AutoLootStartup $InstallationRoot
    Resume-AutoLoot $InstallationRoot
    Write-Host 'Installation complete. AutoLoot will start automatically with your games and at Windows sign-in.'
}

function Uninstall-AutoLoot([string]$InstallationRoot, [switch]$SkipAutoStart) {
    Stop-AutoLootInstallation $InstallationRoot
    if (-not $SkipAutoStart) {
        $previous = Get-AutoLootPreviousRoot
        if ($previous -and $previous -eq $InstallationRoot) { Remove-Item -LiteralPath (Get-AutoLootStartupPath) }
    }
    Write-Host 'Automatic startup removed. You can now delete this folder.'
}

# Dot-sourcing exposes the same lifecycle functions to isolated Windows tests.
if ($MyInvocation.InvocationName -eq '.') { return }
if (-not $Action) { throw 'Choose Install, Prepare, Configure, Pause, Resume or Uninstall.' }
New-Item -ItemType Directory -Path (Join-Path $Root 'evidence') -Force | Out-Null
Start-Transcript -LiteralPath (Join-Path $Root ('evidence\' + $Action + '-AutoLoot.log')) -Force | Out-Null
try {
    switch ($Action) {
        'Install' { Install-AutoLoot $Root }
        'Prepare' { Prepare-AutoLoot $Root $StatePath -SkipAutoStart:$NoAutoStart }
        'Configure' { Configure-AutoLoot $Root $StatePath -SkipAutoStart:$NoAutoStart }
        'Pause' { Pause-AutoLoot $Root }
        'Resume' { Resume-AutoLoot $Root }
        'Uninstall' { Uninstall-AutoLoot $Root -SkipAutoStart:$NoAutoStart }
    }
} catch {
    Write-Output $_
    exit 1
} finally { Stop-Transcript | Out-Null }
