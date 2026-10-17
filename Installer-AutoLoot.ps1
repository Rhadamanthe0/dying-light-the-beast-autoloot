$ErrorActionPreference = 'Stop'
$taskRoot = $PSScriptRoot
$taskVenvPython = Join-Path $taskRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskVenvPython -PathType Leaf)) {
    $taskPython = $null
    foreach ($taskCommand in @('py', 'python')) {
        if (-not (Get-Command $taskCommand -ErrorAction SilentlyContinue)) { continue }
        $taskArguments = if ($taskCommand -eq 'py') { @('-3', '-c', 'import sys; print(sys.executable)') } else { @('-c', 'import sys; print(sys.executable)') }
        $taskCandidate = (& $taskCommand @taskArguments | Select-Object -Last 1)
        if ($LASTEXITCODE -eq 0 -and $taskCandidate -and (Test-Path -LiteralPath $taskCandidate.Trim() -PathType Leaf)) { $taskPython = $taskCandidate.Trim(); break }
    }
    if (-not $taskPython) { throw 'Installer Python 64 bits 3.11 ou plus depuis https://www.python.org/downloads/windows/ puis relancer.' }
    & $taskPython -c 'import struct,sys; sys.exit(0 if sys.version_info >= (3,11) and struct.calcsize(chr(80))==8 else 1)'
    if ($LASTEXITCODE -ne 0) { throw 'Python 64 bits 3.11 ou plus est necessaire.' }
    & $taskPython -m venv (Join-Path $taskRoot '.venv')
    if ($LASTEXITCODE -ne 0) { throw 'Creation de l environnement Python impossible.' }
}
& $taskVenvPython -m pip install --disable-pip-version-check -r (Join-Path $taskRoot 'requirements.txt')
if ($LASTEXITCODE -ne 0) { throw 'Installation des dependances impossible.' }
& $taskVenvPython (Join-Path $taskRoot 'tools\autoloot_runtime.py') --dummy
if ($LASTEXITCODE -ne 0) { throw 'Le controle hors jeu a echoue. Consulter le resultat affiche.' }
Write-Host 'Installation et controles hors jeu termines. Charger une partie puis utiliser Lancer-AutoLoot.cmd.'
