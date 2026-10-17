$ErrorActionPreference = 'Stop'
$taskPython = Join-Path $PSScriptRoot '.venv\Scripts\python.exe'
if (-not (Test-Path -LiteralPath $taskPython -PathType Leaf)) { throw 'Executer Installer-AutoLoot.cmd avant ce controle.' }
& $taskPython (Join-Path $PSScriptRoot 'tools\autoloot_runtime.py') --dummy
if ($LASTEXITCODE -ne 0) { throw 'Les controles hors jeu ont echoue.' }
Write-Host 'Controles hors jeu reussis.'
